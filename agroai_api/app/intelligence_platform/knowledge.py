"""Tenant knowledge for grounding intelligence ("what does *this* organization's data say?").

Retrieval v1 is lexical: PostgreSQL full-text search over a generated
``tsvector`` with the language-neutral ``simple`` configuration, OR-matched
query terms with prefix matching, ranked by ``ts_rank_cd``. It needs no new
infrastructure and keeps provenance exact (every hit is a stored chunk of a
stored document). Semantic retrieval can be added behind the same contract by
adding an embedding column; callers would not change.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.intelligence_platform.contract import to_naive_utc, valid_collection, validate_metadata
from app.intelligence_platform.ownership import owned
from app.models.intelligence_platform import KnowledgeChunk, KnowledgeDocument
from app.platform_api.principal import PlatformPrincipal


MAX_DOCUMENT_CHARS = 1_000_000
MAX_DOCUMENTS_PER_PROJECT = 2_000
MAX_BYTES_PER_PROJECT = 50 * 1024 * 1024
CHUNK_CHARS = 1_200
CHUNK_OVERLAP = 200
_TERM = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "be", "with",
    "what", "which", "how", "why", "when", "does", "do", "my", "our", "this", "that", "it", "at", "by", "from",
    "should", "can", "we", "i", "you", "about", "as", "if", "into", "than", "then", "there", "their",
}


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="document", min_length=1, max_length=40)
    label: str | None = Field(default=None, max_length=200)
    uri: str | None = Field(default=None, max_length=1_000, description="Informational only; never fetched.")


class KnowledgeDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    text: str | None = Field(default=None, min_length=1, max_length=MAX_DOCUMENT_CHARS)
    file_id: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)
    source: KnowledgeSource = Field(default_factory=KnowledgeSource)
    observed_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("collection")
    @classmethod
    def safe_collection(cls, value: str) -> str:
        if not valid_collection(value):
            raise ValueError("collection names are lowercase letters, digits, '.', '_' or '-' (max 64)")
        return value

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_metadata(value)

    @model_validator(mode="after")
    def one_body(self) -> "KnowledgeDocumentCreate":
        if bool(self.text) == bool(self.file_id):
            raise ValueError("provide exactly one of text or file_id")
        return self


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collections: list[str] = Field(min_length=1, max_length=5)
    query: str = Field(min_length=2, max_length=1_000)
    max_results: int = Field(default=6, ge=1, le=20)

    @field_validator("collections")
    @classmethod
    def safe_collections(cls, value: list[str]) -> list[str]:
        if not all(valid_collection(item) for item in value):
            raise ValueError("invalid collection name")
        return list(dict.fromkeys(value))


def chunk_text(value: str) -> list[str]:
    text = re.sub(r"[ \t\r\f\v]+", " ", value.replace("\x00", "")).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + CHUNK_CHARS)
        if end < length:
            window = text[start:end]
            # Prefer a paragraph, then sentence, then word boundary.
            for marker in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(marker)
                if cut > CHUNK_CHARS // 2:
                    end = start + cut + len(marker)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def query_terms(query: str, *, limit: int = 24) -> list[str]:
    terms: list[str] = []
    for match in _TERM.finditer(query.lower()):
        term = match.group(0)
        if len(term) < 2 or term in _STOPWORDS or term in terms:
            continue
        terms.append(term[:60])
        if len(terms) >= limit:
            break
    return terms


def _owned_documents(db: Session, principal: PlatformPrincipal):
    return owned(db.query(KnowledgeDocument), KnowledgeDocument, principal)


def ingest(db: Session, principal: PlatformPrincipal, payload: KnowledgeDocumentCreate) -> tuple[KnowledgeDocument, bool]:
    """Create or (by external_id) refresh a document. Returns (document, changed)."""
    file_row = None
    if payload.file_id:
        from app.intelligence_platform.files import owned_file

        file_row = owned_file(db, principal, payload.file_id)
        if file_row.kind not in {"document", "text"} or not file_row.extracted_text:
            raise HTTPException(status_code=422, detail={"code": "knowledge_file_has_no_text"})
        body = file_row.extracted_text
    else:
        body = str(payload.text)
    body = body[:MAX_DOCUMENT_CHARS]
    chunks = chunk_text(body)
    if not chunks:
        raise HTTPException(status_code=422, detail={"code": "knowledge_document_empty"})
    content_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    byte_size = len(body.encode("utf-8"))

    existing = None
    if payload.external_id:
        existing = (
            _owned_documents(db, principal)
            .filter(
                KnowledgeDocument.collection == payload.collection,
                KnowledgeDocument.external_id == payload.external_id,
                # Exact scope: a project-wide key never refreshes (overwrites)
                # a workspace's document that happens to share an external_id.
                KnowledgeDocument.workspace_id.is_(None)
                if principal.workspace_id is None
                else KnowledgeDocument.workspace_id == principal.workspace_id,
            )
            .with_for_update()
            .first()
        )

    # Quota is per project by design: deliberately not workspace-scoped.
    used_docs, used_bytes = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.organization_id == principal.organization_id,
            KnowledgeDocument.api_project_id == principal.api_project_id,
        )
        .with_entities(func.count(KnowledgeDocument.id), func.coalesce(func.sum(KnowledgeDocument.byte_size), 0))
        .one()
    )
    if existing is None and int(used_docs) >= MAX_DOCUMENTS_PER_PROJECT:
        raise HTTPException(status_code=409, detail={"code": "knowledge_document_quota_exceeded", "limit": MAX_DOCUMENTS_PER_PROJECT})
    projected = int(used_bytes) - (int(existing.byte_size) if existing else 0) + byte_size
    if projected > MAX_BYTES_PER_PROJECT:
        raise HTTPException(status_code=409, detail={"code": "knowledge_storage_quota_exceeded", "limit_bytes": MAX_BYTES_PER_PROJECT})

    if existing is not None and existing.content_sha256 == content_sha and existing.title == payload.title:
        # Same searchable text (body + title header): refresh descriptive
        # metadata only; chunks stay valid.
        existing.source_type = payload.source.type
        existing.source_label = payload.source.label
        existing.source_uri = payload.source.uri
        existing.observed_at = to_naive_utc(payload.observed_at) or existing.observed_at
        existing.metadata_json = payload.metadata
        # The document's source is what was just ingested: a new upload (or
        # inline text) replaces the previous, possibly expiring, file reference.
        existing.file_id = file_row.id if file_row is not None else None
        existing.updated_at = datetime.utcnow()
        db.commit()
        return existing, False

    document = existing or KnowledgeDocument(
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        workspace_id=principal.workspace_id,
        collection=payload.collection,
        external_id=payload.external_id,
    )
    document.title = payload.title
    document.source_type = payload.source.type
    document.source_label = payload.source.label
    document.source_uri = payload.source.uri
    document.observed_at = to_naive_utc(payload.observed_at)
    document.metadata_json = payload.metadata
    document.content_sha256 = content_sha
    document.byte_size = byte_size
    document.chunk_count = len(chunks)
    document.file_id = file_row.id if file_row is not None else None
    document.status = "ready"
    document.updated_at = datetime.utcnow()
    if existing is None:
        db.add(document)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "knowledge_document_conflict"}) from exc
    if existing is not None:
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete(synchronize_session=False)
    db.add_all(
        KnowledgeChunk(
            document_id=document.id,
            organization_id=principal.organization_id,
            api_project_id=principal.api_project_id,
            workspace_id=principal.workspace_id,
            collection=payload.collection,
            ordinal=index,
            # Contextual header: the title is searchable and travels with every passage.
            text=f"{payload.title}\n{piece}",
        )
        for index, piece in enumerate(chunks)
    )
    db.commit()
    return document, True


def owned_document(db: Session, principal: PlatformPrincipal, document_id: str) -> KnowledgeDocument:
    row = _owned_documents(db, principal).filter(KnowledgeDocument.id == document_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "knowledge_document_not_found"})
    return row


def delete_document(db: Session, principal: PlatformPrincipal, document_id: str) -> None:
    row = owned_document(db, principal, document_id)
    db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == row.id,
        KnowledgeChunk.organization_id == principal.organization_id,
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


def known_collections(db: Session, principal: PlatformPrincipal) -> list[dict[str, Any]]:
    rows = (
        _owned_documents(db, principal)
        .with_entities(
            KnowledgeDocument.collection,
            func.count(KnowledgeDocument.id),
            func.coalesce(func.sum(KnowledgeDocument.byte_size), 0),
            func.max(KnowledgeDocument.updated_at),
        )
        .group_by(KnowledgeDocument.collection)
        .order_by(KnowledgeDocument.collection.asc())
        .all()
    )
    return [
        {
            "name": name,
            "documents": int(count),
            "bytes": int(size),
            "updated_at": updated.isoformat() if updated else None,
        }
        for name, count, size, updated in rows
    ]


def _hit(chunk_id: str, document: KnowledgeDocument, text: str, score: float) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "document_id": document.id,
        "collection": document.collection,
        "title": document.title,
        "text": text[:1_500],
        "score": round(float(score), 6),
        "source": {
            "type": document.source_type,
            "label": document.source_label,
            "uri": document.source_uri,
            "external_id": document.external_id,
        },
        "observed_at": document.observed_at.isoformat() if document.observed_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


def candidate_chunks(
    db: Session,
    principal: PlatformPrincipal,
    *,
    collections: list[str],
    query: str,
    max_results: int,
) -> list[tuple[str, str, str, float]]:
    """Ranked (chunk_id, document_id, text, score) for this tenant and project only."""
    terms = query_terms(query)
    if not terms:
        return []
    if db.get_bind().dialect.name == "postgresql":
        tsquery = " | ".join(f"{term}:*" if len(term) >= 4 else term for term in terms)
        rows = db.execute(
            sql_text(
                """
                SELECT c.id, c.document_id, c.text, ts_rank_cd(c.search_vector, q) AS score
                FROM platform_knowledge_chunks AS c, to_tsquery('simple', :tsquery) AS q
                WHERE c.organization_id = :organization_id
                  AND c.api_project_id = :api_project_id
                  AND (CAST(:workspace_id AS VARCHAR) IS NULL OR c.workspace_id = :workspace_id)
                  AND c.collection = ANY(:collections)
                  AND c.search_vector @@ q
                ORDER BY score DESC, c.id ASC
                LIMIT :limit
                """
            ),
            {
                "tsquery": tsquery,
                "organization_id": principal.organization_id,
                "api_project_id": principal.api_project_id,
                "workspace_id": principal.workspace_id,
                "collections": list(collections),
                "limit": int(max_results),
            },
        ).all()
        scored = [(row[0], row[1], row[2], float(row[3])) for row in rows]
    else:
        candidates = (
            owned(db.query(KnowledgeChunk.id, KnowledgeChunk.document_id, KnowledgeChunk.text), KnowledgeChunk, principal)
            .filter(KnowledgeChunk.collection.in_(collections))
            .limit(5_000)
            .all()
        )
        scored = []
        for chunk_id, document_id, body in candidates:
            lowered = body.lower()
            score = sum(lowered.count(term) for term in terms) / (1 + len(lowered) / 1_000)
            if score > 0:
                scored.append((chunk_id, document_id, body, score))
        scored.sort(key=lambda item: (-item[3], item[0]))
        scored = scored[:max_results]
    return scored


def search(
    db: Session,
    principal: PlatformPrincipal,
    *,
    collections: list[str],
    query: str,
    max_results: int,
) -> list[dict[str, Any]]:
    scored = candidate_chunks(db, principal, collections=collections, query=query, max_results=max_results)
    if not scored:
        return []
    documents = {
        row.id: row
        for row in _owned_documents(db, principal)
        .filter(KnowledgeDocument.id.in_({item[1] for item in scored}))
        .all()
    }
    return [
        _hit(chunk_id, documents[document_id], body, score)
        for chunk_id, document_id, body, score in scored
        if document_id in documents
    ]


def public_document(row: KnowledgeDocument) -> dict[str, Any]:
    return {
        "id": row.id,
        "object": "agroai.knowledge_document",
        "collection": row.collection,
        "title": row.title,
        "external_id": row.external_id,
        "source": {"type": row.source_type, "label": row.source_label, "uri": row.source_uri},
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "metadata": dict(row.metadata_json or {}),
        "content_sha256": row.content_sha256,
        "bytes": int(row.byte_size),
        "chunks": int(row.chunk_count),
        "file_id": row.file_id,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

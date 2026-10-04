"""Customer files for AGRO-AI Intelligence.

Security model:

* Bytes arrive only by direct upload. AGRO-AI never fetches a caller URL, so
  there is no SSRF surface and no remote-content trust decision.
* Type is decided by content sniffing; the declared type must agree with the
  sniffed type or the upload is rejected (no MIME confusion).
* Every kind has a hard byte cap enforced while streaming, before storage.
* Images are stored in the tenant-namespaced R2/S3 object store and read back
  with tenant/namespace and checksum verification. Documents are reduced to
  bounded extracted text; the original bytes are not retained.
* A file id is resolved only together with the caller's organization and API
  project. A foreign id is indistinguishable from a missing one.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.intelligence_platform.ownership import owned
from app.models.intelligence_platform import IntelligenceFile
from app.platform_api.principal import PlatformPrincipal


IMAGE_MAX_BYTES = 8 * 1024 * 1024
PDF_MAX_BYTES = 15 * 1024 * 1024
TEXT_MAX_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 200_000
MAX_PDF_PAGES = 200
DEFAULT_RETENTION_DAYS = 30
MAX_ACTIVE_FILES_PER_PROJECT = 1_000
# Aggregate per-project bounds (independent of the 50 MB knowledge quota):
# stored object bytes (R2) and extracted text kept in PostgreSQL.
MAX_OBJECT_BYTES_PER_PROJECT = 1024 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS_PER_PROJECT = 25_000_000

_TEXT_TYPES = {"text/plain", "text/csv", "text/markdown", "application/json"}
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class SniffedType:
    kind: str  # image | document | text
    content_type: str
    max_bytes: int


def _namespace(principal: PlatformPrincipal) -> str:
    return f"intelligence-{principal.api_project_id}"


def sniff(head: bytes, declared: str | None) -> SniffedType:
    declared_type = str(declared or "").split(";", 1)[0].strip().lower()
    declared_type = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "text/x-markdown": "text/markdown"}.get(
        declared_type, declared_type
    )
    if head.startswith(b"\xff\xd8\xff"):
        sniffed = SniffedType("image", "image/jpeg", IMAGE_MAX_BYTES)
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed = SniffedType("image", "image/png", IMAGE_MAX_BYTES)
    elif len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        sniffed = SniffedType("image", "image/webp", IMAGE_MAX_BYTES)
    elif head.startswith(b"%PDF-"):
        sniffed = SniffedType("document", "application/pdf", PDF_MAX_BYTES)
    elif declared_type in _TEXT_TYPES:
        if b"\x00" in head:
            raise HTTPException(status_code=415, detail={"code": "file_content_type_mismatch"})
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            # The head may split a multi-byte character; only reject clear binary.
            if exc.start < len(head) - 4:
                raise HTTPException(status_code=415, detail={"code": "file_text_must_be_utf8"}) from exc
        sniffed = SniffedType("text", declared_type, TEXT_MAX_BYTES)
    else:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "file_type_not_supported",
                "message": "Supported: JPEG, PNG, WebP images; PDF documents; UTF-8 text, CSV, Markdown, JSON.",
            },
        )
    # Declared type must agree with content. Generic declarations are allowed
    # because many HTTP clients send them for every upload.
    if declared_type and declared_type not in {"application/octet-stream", sniffed.content_type}:
        raise HTTPException(
            status_code=415,
            detail={"code": "file_content_type_mismatch", "declared": declared_type[:100], "detected": sniffed.content_type},
        )
    return sniffed


def _safe_filename(value: str | None) -> str:
    name = os.path.basename(str(value or "upload")).strip()
    return (_SAFE_FILENAME.sub("_", name)[:200] or "upload").strip("._ ") or "upload"


class PdfPageLimitExceeded(ValueError):
    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} pages")
        self.pages = pages


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError("encrypted_pdf")
    pages = len(reader.pages)
    if pages > MAX_PDF_PAGES:
        raise PdfPageLimitExceeded(pages)
    parts: list[str] = []
    total = 0
    for page in reader.pages[:MAX_PDF_PAGES]:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)
            total += len(text)
        if total >= MAX_EXTRACTED_CHARS:
            break
    return "\n\n".join(parts)[:MAX_EXTRACTED_CHARS], pages


def project_file_usage(db: Session, principal: PlatformPrincipal) -> dict[str, int]:
    """Project-wide usage (all workspaces). A 'deleting' tombstone still
    occupies object storage until its delete succeeds."""
    from sqlalchemy import func

    base = db.query(IntelligenceFile).filter(
        IntelligenceFile.organization_id == principal.organization_id,
        IntelligenceFile.api_project_id == principal.api_project_id,
    )
    files = base.filter(IntelligenceFile.status == "available").count()
    object_bytes = (
        base.filter(IntelligenceFile.status.in_(["available", "deleting"]), IntelligenceFile.storage_uri.isnot(None))
        .with_entities(func.coalesce(func.sum(IntelligenceFile.size_bytes), 0))
        .scalar()
    )
    text_chars = (
        base.filter(IntelligenceFile.status == "available")
        .with_entities(func.coalesce(func.sum(func.length(IntelligenceFile.extracted_text)), 0))
        .scalar()
    )
    return {"files": int(files), "object_bytes": int(object_bytes or 0), "text_chars": int(text_chars or 0)}


def _quota_error(usage: dict[str, int], *, object_bytes: int, text_chars: int) -> dict[str, Any] | None:
    if usage["files"] + 1 > MAX_ACTIVE_FILES_PER_PROJECT:
        return {"code": "file_quota_exceeded", "limit": MAX_ACTIVE_FILES_PER_PROJECT}
    if usage["object_bytes"] + object_bytes > MAX_OBJECT_BYTES_PER_PROJECT:
        return {"code": "file_storage_quota_exceeded", "limit_bytes": MAX_OBJECT_BYTES_PER_PROJECT, "used_bytes": usage["object_bytes"]}
    if usage["text_chars"] + text_chars > MAX_EXTRACTED_TEXT_CHARS_PER_PROJECT:
        return {"code": "file_text_quota_exceeded", "limit_characters": MAX_EXTRACTED_TEXT_CHARS_PER_PROJECT, "used_characters": usage["text_chars"]}
    return None


def lock_project(db: Session, principal: PlatformPrincipal) -> None:
    """Serialize quota decisions for one API project (row lock until commit)."""
    from app.models.platform_api import ApiProject

    db.query(ApiProject.id).filter(ApiProject.id == principal.api_project_id).with_for_update().first()


def _object_store():
    from app.services.object_storage import get_object_store, object_storage_configured

    if not object_storage_configured():
        return None
    return get_object_store()


async def accept_upload(
    db: Session,
    principal: PlatformPrincipal,
    upload: UploadFile,
    *,
    purpose: str,
) -> IntelligenceFile:
    if purpose not in {"attachment", "knowledge"}:
        raise HTTPException(status_code=422, detail={"code": "file_purpose_invalid"})
    # Fast fail before reading the body; authoritative re-check below.
    early = _quota_error(project_file_usage(db, principal), object_bytes=0, text_chars=0)
    db.rollback()
    if early is not None:
        raise HTTPException(status_code=409, detail=early)

    head = await upload.read(512)
    sniffed = sniff(head, upload.content_type)
    digest = hashlib.sha256(head)
    size = len(head)
    spool = tempfile.NamedTemporaryFile(prefix="agroai-intel-", delete=False)
    try:
        spool.write(head)
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > sniffed.max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "file_too_large", "max_bytes": sniffed.max_bytes, "kind": sniffed.kind},
                )
            digest.update(chunk)
            spool.write(chunk)
        spool.flush()
        spool.close()
        if size == 0:
            raise HTTPException(status_code=422, detail={"code": "file_empty"})
        sha256 = digest.hexdigest()
        filename = _safe_filename(upload.filename)
        row = IntelligenceFile(
            organization_id=principal.organization_id,
            api_project_id=principal.api_project_id,
            workspace_id=principal.workspace_id,
            created_by_api_key_id=principal.api_key_id,
            filename=filename,
            content_type=sniffed.content_type,
            kind=sniffed.kind,
            purpose=purpose,
            size_bytes=size,
            sha256=sha256,
            status="available",
            expires_at=datetime.utcnow() + timedelta(days=DEFAULT_RETENTION_DAYS),
        )
        if sniffed.kind == "image":
            if purpose != "attachment":
                raise HTTPException(status_code=422, detail={"code": "knowledge_requires_text_or_pdf"})
            store = _object_store()
            if store is None:
                raise HTTPException(status_code=503, detail={"code": "file_storage_unavailable"})
            stored = await asyncio.to_thread(
                store.put_path,
                spool.name,
                tenant_id=str(principal.organization_id),
                connection_id=_namespace(principal),
                filename=filename,
                content_type=sniffed.content_type,
                expected_sha256=sha256,
                expected_size=size,
                # Marker first: if the row below never commits (crash, DB
                # error), the shared pending-object reconciler removes the
                # orphan after its grace period.
                pending_registration=True,
            )
            row.storage_uri = stored.uri
        else:
            with open(spool.name, "rb") as handle:
                data = handle.read()
            if sniffed.kind == "document":
                try:
                    text, pages = await asyncio.to_thread(extract_pdf_text, data)
                except PdfPageLimitExceeded as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "document_page_limit_exceeded",
                            "message": f"PDFs may have at most {MAX_PDF_PAGES} pages; this one has {exc.pages}. Split it or add it to knowledge in parts.",
                            "max_pages": MAX_PDF_PAGES,
                        },
                    ) from exc
                except Exception as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={"code": "document_unreadable", "message": "The PDF could not be read (encrypted or malformed)."},
                    ) from exc
                row.page_count = pages
            else:
                try:
                    text = data.decode("utf-8", errors="strict")[:MAX_EXTRACTED_CHARS]
                except UnicodeDecodeError as exc:
                    # The 512-byte sniff tolerates a split trailing character;
                    # the whole body must still be valid UTF-8.
                    raise HTTPException(status_code=415, detail={"code": "file_text_must_be_utf8"}) from exc
            text = text.replace("\x00", "").strip()
            row.extracted_text = text
            row.extraction_status = "extracted" if text else "empty"
        # Authoritative quota decision, serialized per project: concurrent
        # uploads cannot all pass a check made before any of them committed.
        lock_project(db, principal)
        exceeded = _quota_error(
            project_file_usage(db, principal),
            object_bytes=size if row.storage_uri else 0,
            text_chars=len(row.extracted_text or ""),
        )
        if exceeded is not None:
            db.rollback()
            if row.storage_uri:
                try:
                    await asyncio.to_thread(
                        _object_store().delete,
                        row.storage_uri,
                        tenant_id=str(principal.organization_id),
                        connection_id=_namespace(principal),
                    )
                except Exception:  # noqa: BLE001 - pending marker lets the reconciler remove it
                    pass
            raise HTTPException(status_code=409, detail=exceeded)
        db.add(row)
        db.commit()
        if row.storage_uri:
            try:
                await asyncio.to_thread(
                    _object_store().promote,
                    row.storage_uri,
                    tenant_id=str(principal.organization_id),
                    connection_id=_namespace(principal),
                )
            except Exception:  # noqa: BLE001 - the reconciler promotes rows it finds registered
                pass
        return row
    finally:
        try:
            spool.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            os.unlink(spool.name)
        except OSError:
            pass


def owned_file(db: Session, principal: PlatformPrincipal, file_id: str, *, for_update: bool = False) -> IntelligenceFile:
    query = owned(db.query(IntelligenceFile), IntelligenceFile, principal).filter(IntelligenceFile.id == file_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if row is None or row.status != "available" or row.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=404, detail={"code": "file_not_found"})
    return row


def read_image_bytes(principal: PlatformPrincipal, row: IntelligenceFile) -> bytes:
    store = _object_store()
    if store is None or not row.storage_uri:
        raise RuntimeError("file_storage_unavailable")
    data = store.read_bytes(
        row.storage_uri,
        max_bytes=IMAGE_MAX_BYTES,
        tenant_id=str(principal.organization_id),
        connection_id=_namespace(principal),
    )
    if hashlib.sha256(data).hexdigest() != row.sha256:
        raise RuntimeError("file_checksum_mismatch")
    return data


def delete_file(db: Session, principal: PlatformPrincipal, file_id: str) -> None:
    row = owned_file(db, principal, file_id, for_update=True)
    _purge(row, principal_org=str(principal.organization_id), namespace=_namespace(principal))
    db.commit()


def _purge(row: IntelligenceFile, *, principal_org: str, namespace: str) -> bool:
    """Remove a file's content. Returns True once nothing customer-owned remains.

    Extracted text is dropped immediately. If the stored object cannot be
    deleted right now, the row becomes a ``deleting`` tombstone that keeps the
    object URI (and is invisible to callers) so the maintenance sweep retries
    until the object is gone — a transient store error never strands an image.
    """
    now = datetime.utcnow()
    row.extracted_text = None
    row.deleted_at = row.deleted_at or now
    if row.storage_uri:
        store = _object_store()
        try:
            if store is None:
                raise RuntimeError("file_storage_unavailable")
            store.delete(row.storage_uri, tenant_id=principal_org, connection_id=namespace)
        except Exception:  # noqa: BLE001 - retried by expire_files
            row.status = "deleting"
            return False
    row.status = "deleted"
    row.storage_uri = None
    return True


def expire_files(db: Session, *, limit: int = 200) -> int:
    """Retention sweep: expire available files and retry pending object deletions."""
    from sqlalchemy import and_, or_

    now = datetime.utcnow()
    rows = (
        db.query(IntelligenceFile)
        .filter(
            or_(
                and_(IntelligenceFile.status == "available", IntelligenceFile.expires_at <= now),
                IntelligenceFile.status == "deleting",
            )
        )
        .order_by(IntelligenceFile.expires_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    purged = 0
    for row in rows:
        purged += int(_purge(row, principal_org=str(row.organization_id), namespace=f"intelligence-{row.api_project_id}"))
    db.commit()
    return purged


def public_file(row: IntelligenceFile) -> dict[str, Any]:
    return {
        "id": row.id,
        "object": "agroai.file",
        "filename": row.filename,
        "content_type": row.content_type,
        "kind": row.kind,
        "purpose": row.purpose,
        "size_bytes": int(row.size_bytes),
        "sha256": row.sha256,
        "page_count": row.page_count,
        "extraction_status": row.extraction_status,
        "extracted_characters": len(row.extracted_text or "") if row.kind != "image" else None,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }

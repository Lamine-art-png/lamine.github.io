"""AGRO-AI Intelligence Platform v1 primitives.

Every row is owned by exactly one (organization, API project) pair, and by
the workspace of the key that created it when that key is workspace
restricted (``workspace_id``). A workspace-restricted key sees only rows of
its workspace; a project-wide key sees the whole project. Rows are
never looked up by id alone: callers always filter by the authenticated
principal's organization and project, so a foreign id behaves exactly like a
missing one. Mirrors alembic 042_intelligence_platform_v1.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func

from app.db.base import Base


def _id(prefix: str):
    return lambda: f"{prefix}_{uuid.uuid4().hex}"


class IntelligenceSession(Base):
    """Bounded, expiring developer-controlled context across intelligence runs."""

    __tablename__ = "platform_intelligence_sessions"
    __table_args__ = (
        Index("ix_intelligence_session_owner_time", "organization_id", "api_project_id", "created_at"),
        Index("ix_intelligence_session_expiry", "status", "expires_at"),
        CheckConstraint("turn_count >= 0", name="ck_intelligence_session_turns_nonnegative"),
    )

    id = Column(String, primary_key=True, default=_id("ses"))
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    created_by_api_key_id = Column(String, nullable=True)
    created_by_user_id = Column(String, nullable=True)
    title = Column(String(200), nullable=True)
    context_json = Column(JSON, nullable=False, default=dict)
    metadata_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="active")
    turn_count = Column(Integer, nullable=False, default=0)
    retention_days = Column(Integer, nullable=False, default=30)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)


class IntelligenceSessionTurn(Base):
    __tablename__ = "platform_intelligence_session_turns"
    __table_args__ = (Index("ix_intelligence_session_turn_order", "session_id", "created_at"),)

    id = Column(String, primary_key=True, default=_id("turn"))
    session_id = Column(String, ForeignKey("platform_intelligence_sessions.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String, nullable=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class IntelligenceFile(Base):
    """A customer file accepted for intelligence: sniffed, size-bounded, tenant-scoped."""

    __tablename__ = "platform_intelligence_files"
    __table_args__ = (
        Index("ix_intelligence_file_owner_time", "organization_id", "api_project_id", "created_at"),
        Index("ix_intelligence_file_expiry", "status", "expires_at"),
        CheckConstraint("size_bytes >= 0", name="ck_intelligence_file_size_nonnegative"),
    )

    id = Column(String, primary_key=True, default=_id("file"))
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    created_by_api_key_id = Column(String, nullable=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    kind = Column(String(20), nullable=False)
    purpose = Column(String(20), nullable=False, default="attachment")
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_uri = Column(String, nullable=True)
    extracted_text = Column(Text, nullable=True)
    extraction_status = Column(String(20), nullable=False, default="not_applicable")
    page_count = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="available")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)


class KnowledgeDocument(Base):
    """Customer knowledge that grounds intelligence; provenance travels with every chunk."""

    __tablename__ = "platform_knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_document_owner_collection", "organization_id", "api_project_id", "collection", "created_at"),
        CheckConstraint("byte_size >= 0", name="ck_knowledge_document_size_nonnegative"),
    )

    id = Column(String, primary_key=True, default=_id("doc"))
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    collection = Column(String(64), nullable=False)
    title = Column(String(300), nullable=False)
    external_id = Column(String(200), nullable=True)
    source_type = Column(String(40), nullable=False, default="document")
    source_label = Column(String(200), nullable=True)
    source_uri = Column(String(1000), nullable=True)
    observed_at = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    content_sha256 = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    file_id = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default="ready")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# external_id is unique per (organization, project, workspace-or-project-wide,
# collection); NULL workspace folds to '' so project-wide documents dedupe too.
Index(
    "uq_knowledge_document_external_id",
    KnowledgeDocument.organization_id,
    KnowledgeDocument.api_project_id,
    func.coalesce(KnowledgeDocument.workspace_id, ""),
    KnowledgeDocument.collection,
    KnowledgeDocument.external_id,
    unique=True,
)


class KnowledgeChunk(Base):
    """Searchable text unit. On PostgreSQL a generated ``search_vector`` column
    (migration-only) backs full-text search with a GIN index."""

    __tablename__ = "platform_knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunk_owner_collection", "organization_id", "api_project_id", "collection"),
        Index("ix_knowledge_chunk_document", "document_id", "ordinal"),
    )

    id = Column(String, primary_key=True, default=_id("chunk"))
    document_id = Column(String, ForeignKey("platform_knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    api_project_id = Column(String, ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    collection = Column(String(64), nullable=False)
    ordinal = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

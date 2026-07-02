"""Operational records for connector setup, uploaded evidence, intelligence runs, reports, and chat memory."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, JSON, String, Text

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class ConnectorConnection(Base):
    __tablename__ = "connector_connections"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    provider = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    status = Column(String, default="not_configured", nullable=False, index=True)
    mode = Column(String, default="manual_upload", nullable=False, index=True)
    required_plan = Column(String, default="free", nullable=False)
    config_json = Column(JSON, default=dict, nullable=False)
    credentials_ref = Column(String, nullable=True)
    last_test_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_connector_tenant_provider", "tenant_id", "provider"),)


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    connector_connection_id = Column(String, ForeignKey("connector_connections.id"), nullable=True, index=True)
    source_type = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    status = Column(String, default="uploaded", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    connector_connection_id = Column(String, ForeignKey("connector_connections.id"), nullable=True, index=True)
    data_source_id = Column(String, ForeignKey("data_sources.id"), nullable=True, index=True)
    job_type = Column(String, nullable=False, index=True)
    status = Column(String, default="queued", nullable=False, index=True)
    input_json = Column(JSON, default=dict, nullable=False)
    output_json = Column(JSON, default=dict, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    data_source_id = Column(String, ForeignKey("data_sources.id"), nullable=True, index=True)
    connector_connection_id = Column(String, ForeignKey("connector_connections.id"), nullable=True, index=True)
    evidence_type = Column(String, nullable=False, index=True)
    field_id = Column(String, nullable=True, index=True)
    block_id = Column(String, nullable=True, index=True)
    occurred_at = Column(DateTime, nullable=True, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    value_json = Column(JSON, default=dict, nullable=False)
    units = Column(String, nullable=True)
    confidence = Column(Float, default=0.75, nullable=False)
    quality_status = Column(String, default="usable", nullable=False, index=True)
    citation_label = Column(String, nullable=False)
    source_excerpt = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (Index("ix_evidence_tenant_type_time", "tenant_id", "evidence_type", "occurred_at"),)


class IntelligenceRun(Base):
    __tablename__ = "intelligence_runs"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    run_type = Column(String, nullable=False, index=True)
    question = Column(Text, nullable=True)
    input_context_json = Column(JSON, default=dict, nullable=False)
    output_json = Column(JSON, default=dict, nullable=False)
    citations_json = Column(JSON, default=list, nullable=False)
    model_provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    status = Column(String, default="completed", nullable=False, index=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    intelligence_run_id = Column(String, ForeignKey("intelligence_runs.id"), nullable=True, index=True)
    artifact_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    body_text = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(String, primary_key=True, default=new_id, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String, default="New chat", nullable=False)
    summary = Column(Text, nullable=True)
    pinned = Column(String, default="false", nullable=False, index=True)
    status = Column(String, default="active", nullable=False, index=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    message_count = Column(Float, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    last_message_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_chat_conversation_tenant_workspace", "tenant_id", "workspace_id", "last_message_at"),
        Index("ix_chat_conversation_user", "tenant_id", "user_id", "last_message_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=new_id, index=True)
    conversation_id = Column(String, ForeignKey("chat_conversations.id"), nullable=False, index=True)
    tenant_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),)

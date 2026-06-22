"""Database records for persisted workbench sessions."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String

from app.db.base import Base


class WorkbenchSessionRecord(Base):
    __tablename__ = "workbench_sessions"

    session_id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    assurance_passport_id = Column(String, ForeignKey("assurance_passports.id"), nullable=True, index=True)
    workspace_name = Column(String, nullable=False)
    mode = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    is_sample_package = Column(String, default="false", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class WorkbenchDataArtifactRecord(Base):
    __tablename__ = "workbench_data_artifacts"

    artifact_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("workbench_sessions.session_id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    source_kind = Column(String, nullable=False, index=True)
    rows_detected = Column(String, nullable=False)
    columns_detected = Column(JSON, nullable=False)
    parse_status = Column(String, nullable=False, index=True)
    warnings = Column(JSON, nullable=False)
    parsed_rows = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WorkbenchAnalysisRecord(Base):
    __tablename__ = "workbench_analyses"

    analysis_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("workbench_sessions.session_id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WorkbenchAuditEventRecord(Base):
    __tablename__ = "workbench_audit_events"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("workbench_sessions.session_id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WorkbenchEvidenceActionRecord(Base):
    __tablename__ = "workbench_evidence_actions"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("workbench_sessions.session_id"), nullable=False, index=True)
    action_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("ix_workbench_evidence_session_action", "session_id", "action_type"),)


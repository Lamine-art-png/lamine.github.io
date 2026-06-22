"""Persistence adapter for Workbench sessions."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.workbench import WorkbenchAnalysisResult, WorkbenchDataArtifact, WorkbenchSession
from app.models.workbench_persistence import (
    WorkbenchAnalysisRecord,
    WorkbenchAuditEventRecord,
    WorkbenchDataArtifactRecord,
    WorkbenchEvidenceActionRecord,
    WorkbenchSessionRecord,
)


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def save_store(db: Session, store: dict[str, Any], *, tenant_id: str | None = None, assurance_passport_id: str | None = None) -> None:
    session = store["session"]
    existing = db.query(WorkbenchSessionRecord).filter_by(session_id=session.session_id).first()
    if not existing:
        existing = WorkbenchSessionRecord(session_id=session.session_id)
        db.add(existing)
    existing.tenant_id = tenant_id or existing.tenant_id
    existing.assurance_passport_id = assurance_passport_id or existing.assurance_passport_id
    existing.workspace_name = session.workspace_name
    existing.mode = session.mode
    existing.status = session.status
    existing.is_sample_package = "true" if store.get("is_sample_package") else "false"
    existing.created_at = session.created_at
    existing.updated_at = session.updated_at

    db.query(WorkbenchDataArtifactRecord).filter_by(session_id=session.session_id).delete()
    for artifact in store.get("artifacts", []):
        db.add(WorkbenchDataArtifactRecord(
            artifact_id=artifact.artifact_id,
            session_id=session.session_id,
            filename=artifact.filename,
            content_type=artifact.content_type,
            source_kind=artifact.source_kind,
            rows_detected=str(artifact.rows_detected),
            columns_detected=artifact.columns_detected,
            parse_status=artifact.parse_status,
            warnings=artifact.warnings,
            parsed_rows=artifact.parsed_rows,
        ))

    db.query(WorkbenchAnalysisRecord).filter_by(session_id=session.session_id).delete()
    analysis = store.get("analysis")
    if analysis:
        db.add(WorkbenchAnalysisRecord(
            analysis_id=analysis.analysis_id,
            session_id=session.session_id,
            payload=_dump(analysis),
            created_at=analysis.created_at,
        ))

    db.query(WorkbenchAuditEventRecord).filter_by(session_id=session.session_id).delete()
    for event in store.get("audit", []):
        db.add(WorkbenchAuditEventRecord(id=f"wba-{uuid.uuid4().hex[:12]}", session_id=session.session_id, payload=event))

    db.query(WorkbenchEvidenceActionRecord).filter_by(session_id=session.session_id).delete()
    for action in store.get("evidence_actions", []):
        db.add(WorkbenchEvidenceActionRecord(
            id=f"wbe-{uuid.uuid4().hex[:12]}",
            session_id=session.session_id,
            action_type=action.get("type", "unknown"),
            payload=action,
        ))
    db.commit()


def load_store(db: Session, session_id: str) -> dict[str, Any] | None:
    row = db.query(WorkbenchSessionRecord).filter_by(session_id=session_id).first()
    if not row:
        return None
    session = WorkbenchSession(
        session_id=row.session_id,
        workspace_name=row.workspace_name,
        mode=row.mode,
        created_at=row.created_at or datetime.utcnow(),
        updated_at=row.updated_at or datetime.utcnow(),
        status=row.status,
    )
    artifacts = [
        WorkbenchDataArtifact(
            artifact_id=artifact.artifact_id,
            session_id=artifact.session_id,
            filename=artifact.filename,
            content_type=artifact.content_type,
            source_kind=artifact.source_kind,
            rows_detected=int(artifact.rows_detected or 0),
            columns_detected=artifact.columns_detected or [],
            parse_status=artifact.parse_status,
            warnings=artifact.warnings or [],
            parsed_rows=artifact.parsed_rows or [],
        )
        for artifact in db.query(WorkbenchDataArtifactRecord).filter_by(session_id=session_id).all()
    ]
    analysis_row = db.query(WorkbenchAnalysisRecord).filter_by(session_id=session_id).order_by(WorkbenchAnalysisRecord.created_at.desc()).first()
    analysis = WorkbenchAnalysisResult(**analysis_row.payload) if analysis_row else None
    audit = [event.payload for event in db.query(WorkbenchAuditEventRecord).filter_by(session_id=session_id).order_by(WorkbenchAuditEventRecord.created_at).all()]
    actions = [action.payload for action in db.query(WorkbenchEvidenceActionRecord).filter_by(session_id=session_id).order_by(WorkbenchEvidenceActionRecord.created_at).all()]
    return {
        "session": session,
        "artifacts": artifacts,
        "analysis": analysis,
        "audit": audit,
        "evidence_actions": actions,
        "is_sample_package": row.is_sample_package == "true",
        "assurance_passport_id": row.assurance_passport_id,
        "tenant_id": row.tenant_id,
    }


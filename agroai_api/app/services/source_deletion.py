from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.models.operational_records import DataSource, EvidenceRecord, IngestionJob
from app.models.saas import UsageEvent
from app.models.task_outbox import TaskOutbox
from app.services.object_storage import get_object_store


_SOURCE_WRITE_ROLES = {"owner", "admin", "manager", "operator"}
_PENDING_JOB_TYPE = "connector_ingest_object"
_RUNNING_STATUS = "running"
_CANCELABLE_STATUSES = {"queued", "retrying", "failed", "cancelled", "succeeded"}


def _organization_id(auth: AuthContext) -> str:
    if auth.organization is None or auth.membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    if auth.membership.role not in _SOURCE_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "source_write_required", "message": "File management requires operator, manager, admin, or owner access."},
        )
    return auth.organization.id


def _job_source_id(job: IngestionJob) -> str | None:
    output = job.output_json if isinstance(job.output_json, dict) else {}
    value = output.get("data_source_id") or job.data_source_id
    return str(value or "") or None


def _source_object_uri(source: DataSource) -> str | None:
    metadata = dict(source.metadata_json or {}) if isinstance(source.metadata_json, dict) else {}
    for candidate in (metadata.get("durable_object_uri"), source.storage_path):
        value = str(candidate or "").strip()
        if value:
            return value
    return None


def _job_object_uri(job: IngestionJob) -> str | None:
    payload = dict(job.input_json or {}) if isinstance(job.input_json, dict) else {}
    output = dict(job.output_json or {}) if isinstance(job.output_json, dict) else {}
    return str(payload.get("object_uri") or output.get("object_uri") or "").strip() or None


def _delete_backing_object(*, uri: str | None, tenant_id: str, connection_id: str | None) -> bool:
    if not uri or uri.startswith("inline://"):
        return False
    try:
        if "://" in uri:
            kwargs: dict[str, Any] = {}
            if connection_id:
                kwargs = {"tenant_id": tenant_id, "connection_id": connection_id}
            get_object_store().delete(uri, **kwargs)
        else:
            Path(uri).unlink(missing_ok=True)
        return True
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "source_object_delete_failed",
                "message": "AGRO-AI could not remove the stored file. The deletion remains recoverable; retry in a moment.",
            },
        ) from exc


def _related_jobs(db: Session, *, tenant_id: str, source_id: str) -> list[IngestionJob]:
    """Return every job that owns or resolved to the source, without a history cap.

    Older ingestion workers persisted ``data_source_id`` only inside ``output_json``.
    Querying the JSON scalar directly keeps deletion complete for arbitrarily large
    tenants and removes the idempotency row so the same file can be uploaded again.
    """
    output_source_id = IngestionJob.output_json["data_source_id"].as_string()
    return (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == tenant_id,
            or_(
                IngestionJob.data_source_id == source_id,
                output_source_id == source_id,
            ),
        )
        .all()
    )


def _record_delete_event(
    db: Session,
    *,
    auth: AuthContext,
    workspace_id: str | None,
    source_ref: str,
    filename: str | None,
    evidence_deleted: int,
    jobs_deleted: int,
    object_deleted: bool,
    pending: bool,
) -> None:
    db.add(
        UsageEvent(
            organization_id=auth.organization.id,
            workspace_id=workspace_id,
            user_id=auth.user.id,
            event_type="source_deleted",
            metric="source_file",
            quantity=1,
            metadata_json={
                "source_ref": source_ref,
                "filename": filename,
                "evidence_deleted": evidence_deleted,
                "jobs_deleted": jobs_deleted,
                "object_deleted": object_deleted,
                "pending_upload": pending,
            },
        )
    )


def _delete_completed_source(db: Session, *, auth: AuthContext, source: DataSource) -> dict[str, Any]:
    tenant_id = _organization_id(auth)
    if source.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    source_id = source.id
    jobs = _related_jobs(db, tenant_id=tenant_id, source_id=source_id)
    if any(job.status == _RUNNING_STATUS for job in jobs):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "source_processing_active", "message": "This file is actively processing. Retry deletion in a few seconds."},
        )

    filename = source.filename
    workspace_id = source.workspace_id
    object_deleted = _delete_backing_object(
        uri=_source_object_uri(source),
        tenant_id=tenant_id,
        connection_id=source.connector_connection_id,
    )

    job_ids = [job.id for job in jobs]
    evidence_deleted = int(
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.data_source_id == source_id)
        .delete(synchronize_session=False)
        or 0
    )
    if job_ids:
        db.query(TaskOutbox).filter(TaskOutbox.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(IngestionJob).filter(IngestionJob.id.in_(job_ids)).delete(synchronize_session=False)
    db.delete(source)
    _record_delete_event(
        db,
        auth=auth,
        workspace_id=workspace_id,
        source_ref=source_id,
        filename=filename,
        evidence_deleted=evidence_deleted,
        jobs_deleted=len(job_ids),
        object_deleted=object_deleted,
        pending=False,
    )
    db.commit()
    return {
        "status": "deleted",
        "source_id": source_id,
        "filename": filename,
        "evidence_deleted": evidence_deleted,
        "jobs_deleted": len(job_ids),
        "object_deleted": object_deleted,
        "pending_upload": False,
    }


def _delete_pending_job(db: Session, *, auth: AuthContext, job_id: str) -> dict[str, Any]:
    tenant_id = _organization_id(auth)
    job = db.get(IngestionJob, job_id)
    if job is None or job.tenant_id != tenant_id or job.job_type != _PENDING_JOB_TYPE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    source_id = _job_source_id(job)
    if source_id:
        source = db.get(DataSource, source_id)
        if source is not None and source.tenant_id == tenant_id:
            return _delete_completed_source(db, auth=auth, source=source)

    if job.status == _RUNNING_STATUS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "source_processing_active", "message": "This file is actively processing. Retry deletion in a few seconds."},
        )

    now = datetime.utcnow()
    if job.status in _CANCELABLE_STATUSES:
        result = db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job.id,
                IngestionJob.tenant_id == tenant_id,
                IngestionJob.status.in_(_CANCELABLE_STATUSES),
            )
            .values(
                status="cancelled",
                cancelled_at=now,
                lease_expires_at=None,
                worker_id=None,
                next_attempt_at=None,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "source_processing_active", "message": "This file began processing. Retry deletion in a few seconds."},
            )
        db.query(TaskOutbox).filter(TaskOutbox.job_id == job.id).delete(synchronize_session=False)
        db.commit()
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source cannot be deleted in its current state")

    db.refresh(job)

    # The worker may finish between the first read and our conditional cancellation.
    # Re-check the durable result after the claim. If a source was created, delete the
    # complete source graph rather than leaving its evidence behind as an orphan.
    completed_source_id = _job_source_id(job)
    if completed_source_id:
        completed_source = db.get(DataSource, completed_source_id)
        if completed_source is not None and completed_source.tenant_id == tenant_id:
            return _delete_completed_source(db, auth=auth, source=completed_source)

    payload = dict(job.input_json or {}) if isinstance(job.input_json, dict) else {}
    filename = str(payload.get("filename") or "") or None
    object_deleted = _delete_backing_object(
        uri=_job_object_uri(job),
        tenant_id=tenant_id,
        connection_id=job.connector_connection_id,
    )
    workspace_id = job.workspace_id
    db.delete(job)
    _record_delete_event(
        db,
        auth=auth,
        workspace_id=workspace_id,
        source_ref=f"job:{job_id}",
        filename=filename,
        evidence_deleted=0,
        jobs_deleted=1,
        object_deleted=object_deleted,
        pending=True,
    )
    db.commit()
    return {
        "status": "deleted",
        "source_id": f"job:{job_id}",
        "filename": filename,
        "evidence_deleted": 0,
        "jobs_deleted": 1,
        "object_deleted": object_deleted,
        "pending_upload": True,
    }


def delete_source_reference(db: Session, *, auth: AuthContext, source_ref: str) -> dict[str, Any]:
    _organization_id(auth)
    if source_ref.startswith("job:"):
        return _delete_pending_job(db, auth=auth, job_id=source_ref.removeprefix("job:"))

    source = db.get(DataSource, source_ref)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return _delete_completed_source(db, auth=auth, source=source)

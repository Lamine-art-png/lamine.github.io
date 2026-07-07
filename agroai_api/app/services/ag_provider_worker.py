from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from app.models.operational_records import ConnectorConnection, IngestionJob
from app.services.ag_connector_runtime import AUTH_ERRORS, RATE_LIMIT_ERRORS, sync_ag_provider
from app.services.ingestion_job_runner import _claim, _complete, _fail_or_retry, job_lease_heartbeat
from app.services.provider_sync_jobs import TASK_TYPE


def _connection_state(db: Session, *, connection_id: str | None, tenant_id: str, state: str, exc: Exception) -> None:
    if not connection_id:
        return
    db.execute(
        update(ConnectorConnection)
        .where(ConnectorConnection.id == connection_id, ConnectorConnection.tenant_id == tenant_id)
        .values(status=state, last_error=str(exc)[:700], updated_at=datetime.utcnow())
    )
    db.commit()


def _retry(
    db: Session,
    *,
    job_id: str,
    connection_id: str | None,
    tenant_id: str,
    worker_id: str,
    exc: Exception,
    retry_state: str,
) -> str:
    result = _fail_or_retry(db, job_id, exc, worker_id=worker_id)
    state = "failed" if result == "failed" else retry_state if result == "retrying" else None
    if state:
        _connection_state(db, connection_id=connection_id, tenant_id=tenant_id, state=state, exc=exc)
    return result


def _reconnect(db: Session, *, job_id: str, exc: Exception, worker_id: str) -> str:
    db.rollback()
    job = db.get(IngestionJob, job_id)
    if job is None:
        return "failed"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.status != "running" or job.worker_id != worker_id:
        return "deferred"
    now = datetime.utcnow()
    result = db.execute(
        update(IngestionJob)
        .where(and_(IngestionJob.id == job_id, IngestionJob.status == "running", IngestionJob.worker_id == worker_id))
        .values(
            status="failed",
            error=str(exc)[:700],
            completed_at=now,
            next_attempt_at=None,
            lease_expires_at=None,
            worker_id=None,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return "deferred"
    if job.connector_connection_id:
        db.execute(
            update(ConnectorConnection)
            .where(
                ConnectorConnection.id == job.connector_connection_id,
                ConnectorConnection.tenant_id == job.tenant_id,
            )
            .values(status="reconnect_required", last_error=str(exc)[:700], updated_at=now)
        )
    db.commit()
    return "failed"


async def process_ag_provider_job(db: Session, *, job_id: str, tenant_id: str, worker_id: str) -> str:
    job = _claim(db, job_id=job_id, tenant_id=tenant_id, worker_id=worker_id)
    if job is None:
        return "deferred"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.job_type != TASK_TYPE:
        return _fail_or_retry(db, job_id, RuntimeError("worker task type mismatch"), worker_id=worker_id)

    connection_id = job.connector_connection_id
    with job_lease_heartbeat(job_id=job_id, tenant_id=tenant_id, worker_id=worker_id) as heartbeat:
        try:
            connection = db.get(ConnectorConnection, connection_id)
            if connection is None or connection.tenant_id != tenant_id:
                raise RuntimeError("provider sync connection is unavailable")
            if connection.provider not in {"wiseconn", "talgil", "openet"}:
                raise RuntimeError("agricultural sync adapter is unavailable")
            connection.status = "syncing"
            connection.updated_at = datetime.utcnow()
            db.commit()

            output = await sync_ag_provider(db, connection=connection)
            if heartbeat.lost:
                db.rollback()
                return "deferred"
            job = db.get(IngestionJob, job_id)
            connection = db.get(ConnectorConnection, connection.id)
            if job is None or connection is None:
                raise RuntimeError("provider sync state disappeared")
            connection.status = "synced"
            connection.last_sync_at = datetime.utcnow()
            connection.last_error = None
            connection.updated_at = datetime.utcnow()
            return _complete(db, job, output, worker_id=worker_id)
        except AUTH_ERRORS as exc:
            return _reconnect(db, job_id=job_id, exc=exc, worker_id=worker_id)
        except RATE_LIMIT_ERRORS as exc:
            return _retry(
                db,
                job_id=job_id,
                connection_id=connection_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                exc=exc,
                retry_state="rate_limited",
            )
        except Exception as exc:
            return _retry(
                db,
                job_id=job_id,
                connection_id=connection_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                exc=exc,
                retry_state="degraded",
            )

from __future__ import annotations

import hashlib
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import ingest_upload
from app.core.config import settings
from app.db.base import SessionLocal
from app.models.hardened_records import DataSourceIdentity, IngestionJobState
from app.models.operational_records import ConnectorConnection, DataSource
from app.services.object_storage import get_object_store


logger = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:700]}"


def _lease_seconds() -> int:
    return max(30, int(getattr(settings, "TASK_QUEUE_LEASE_SECONDS", 120) or 120))


def _heartbeat_interval_seconds() -> float:
    return max(1.0, min(30.0, _lease_seconds() / 3.0))


def _claim(db: Session, *, job_id: str, tenant_id: str, worker_id: str) -> IngestionJobState | None:
    now = datetime.utcnow()
    current = db.get(IngestionJobState, job_id)
    if current is None or current.tenant_id != tenant_id:
        return None
    if current.status in {"succeeded", "failed", "cancelled"}:
        return current
    if current.next_attempt_at and current.next_attempt_at > now:
        return None
    statement = (
        update(IngestionJobState)
        .where(
            and_(
                IngestionJobState.id == job_id,
                IngestionJobState.tenant_id == tenant_id,
                IngestionJobState.status.in_(["queued", "retrying", "running"]),
                or_(IngestionJobState.lease_expires_at.is_(None), IngestionJobState.lease_expires_at <= now),
                IngestionJobState.cancelled_at.is_(None),
            )
        )
        .values(
            status="running",
            attempt_count=IngestionJobState.attempt_count + 1,
            worker_id=worker_id,
            last_heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=_lease_seconds()),
            updated_at=now,
        )
    )
    result = db.execute(statement)
    db.commit()
    if result.rowcount != 1:
        return None
    return db.get(IngestionJobState, job_id)


def _renew_lease(db: Session, *, job_id: str, tenant_id: str, worker_id: str) -> bool:
    now = datetime.utcnow()
    statement = (
        update(IngestionJobState)
        .where(
            and_(
                IngestionJobState.id == job_id,
                IngestionJobState.tenant_id == tenant_id,
                IngestionJobState.status == "running",
                IngestionJobState.worker_id == worker_id,
                IngestionJobState.cancelled_at.is_(None),
            )
        )
        .values(
            last_heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=_lease_seconds()),
            updated_at=now,
        )
    )
    result = db.execute(statement)
    db.commit()
    return result.rowcount == 1


def _renew_lease_once(*, job_id: str, tenant_id: str, worker_id: str) -> bool:
    db = SessionLocal()
    try:
        return _renew_lease(db, job_id=job_id, tenant_id=tenant_id, worker_id=worker_id)
    except Exception:
        db.rollback()
        logger.exception("connector job lease heartbeat failed job_id=%s worker_id=%s", job_id, worker_id)
        return False
    finally:
        db.close()


class JobLeaseHeartbeat:
    def __init__(self, *, job_id: str, tenant_id: str, worker_id: str):
        self.job_id = job_id
        self.tenant_id = tenant_id
        self.worker_id = worker_id
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"job-lease-{job_id[:12]}", daemon=True)

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, _heartbeat_interval_seconds() + 1.0))

    def _run(self) -> None:
        interval = _heartbeat_interval_seconds()
        while not self._stop.wait(interval):
            if not _renew_lease_once(job_id=self.job_id, tenant_id=self.tenant_id, worker_id=self.worker_id):
                self._lost.set()
                return


@contextmanager
def job_lease_heartbeat(*, job_id: str, tenant_id: str, worker_id: str) -> Iterator[JobLeaseHeartbeat]:
    heartbeat = JobLeaseHeartbeat(job_id=job_id, tenant_id=tenant_id, worker_id=worker_id)
    heartbeat.start()
    try:
        yield heartbeat
    finally:
        heartbeat.stop()


def _complete(db: Session, job: IngestionJobState, output: dict, *, worker_id: str) -> str:
    now = datetime.utcnow()
    statement = (
        update(IngestionJobState)
        .where(
            and_(
                IngestionJobState.id == job.id,
                IngestionJobState.tenant_id == job.tenant_id,
                IngestionJobState.status == "running",
                IngestionJobState.worker_id == worker_id,
                IngestionJobState.cancelled_at.is_(None),
            )
        )
        .values(
            status="succeeded",
            output_json=output,
            error=None,
            completed_at=now,
            lease_expires_at=None,
            worker_id=None,
            last_heartbeat_at=now,
            updated_at=now,
        )
    )
    result = db.execute(statement)
    if result.rowcount != 1:
        db.rollback()
        return "deferred"
    db.commit()
    return "succeeded"


def _fail_or_retry(db: Session, job_id: str, exc: Exception, *, worker_id: str) -> str:
    db.rollback()
    job = db.get(IngestionJobState, job_id)
    if job is None:
        return "failed"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.status != "running" or job.worker_id != worker_id:
        return "deferred"

    terminal = int(job.attempt_count or 0) >= int(job.max_attempts or 5)
    status = "failed" if terminal else "retrying"
    now = datetime.utcnow()
    values = {
        "status": status,
        "error": _safe_error(exc),
        "lease_expires_at": None,
        "worker_id": None,
        "updated_at": now,
        "next_attempt_at": None if terminal else now + timedelta(seconds=min(300, 15 * (2 ** max(0, int(job.attempt_count or 1) - 1)))),
    }
    if terminal:
        values["completed_at"] = now

    statement = (
        update(IngestionJobState)
        .where(
            and_(
                IngestionJobState.id == job_id,
                IngestionJobState.status == "running",
                IngestionJobState.worker_id == worker_id,
            )
        )
        .values(**values)
    )
    result = db.execute(statement)
    if result.rowcount != 1:
        db.rollback()
        return "deferred"
    db.commit()
    return status


def _remove_transient_copy(path_value: str | None, durable_uri: str) -> None:
    if not path_value or path_value == durable_uri or "://" in path_value:
        return
    try:
        Path(path_value).unlink(missing_ok=True)
    except OSError:
        return


def _delete_redundant_object(*, uri: str, tenant_id: str, connection_id: str) -> bool:
    try:
        get_object_store().delete(uri, tenant_id=tenant_id, connection_id=connection_id)
        return True
    except Exception:
        logger.exception(
            "redundant connector object cleanup failed tenant_id=%s connection_id=%s",
            tenant_id,
            connection_id,
        )
        return False


def _json_safe_completion(result: dict, *, source_id: str | None, durable_uri: str, checksum: str) -> dict:
    warnings = result.get("warnings") or []
    return {
        "deduplicated": False,
        "data_source_id": source_id,
        "rows_parsed": int(result.get("rows_parsed") or 0),
        "evidence_records_created": int(result.get("evidence_records_created") or 0),
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "object_uri": durable_uri,
        "content_sha256": checksum,
    }


def process_ingestion_job(db: Session, *, job_id: str, tenant_id: str, worker_id: str) -> str:
    job = _claim(db, job_id=job_id, tenant_id=tenant_id, worker_id=worker_id)
    if job is None:
        return "deferred"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status

    with job_lease_heartbeat(job_id=job_id, tenant_id=tenant_id, worker_id=worker_id) as heartbeat:
        try:
            payload = dict(job.input_json or {})
            connection_id = str(payload.get("connection_id") or job.connector_connection_id or "")
            connection = db.get(ConnectorConnection, connection_id)
            if connection is None or connection.tenant_id != tenant_id:
                raise RuntimeError("connector connection is unavailable for queued ingestion")

            durable_uri = str(payload.get("object_uri") or "")
            content_sha256 = str(payload.get("content_sha256") or "").strip().lower()
            expected_size = int(payload.get("size_bytes") or -1)
            if not durable_uri:
                raise RuntimeError("queued ingestion is missing its durable object URI")
            if len(content_sha256) != 64:
                raise RuntimeError("queued ingestion is missing its expected content checksum")
            if expected_size < 0:
                raise RuntimeError("queued ingestion is missing its expected object size")

            duplicate = db.query(DataSourceIdentity).filter(
                DataSourceIdentity.tenant_id == tenant_id,
                DataSourceIdentity.connector_connection_id == connection.id,
                DataSourceIdentity.content_sha256 == content_sha256,
            ).first()
            if duplicate is not None:
                if heartbeat.lost:
                    db.rollback()
                    return "deferred"
                deleted = _delete_redundant_object(
                    uri=durable_uri,
                    tenant_id=tenant_id,
                    connection_id=connection.id,
                )
                return _complete(
                    db,
                    job,
                    {
                        "deduplicated": True,
                        "data_source_id": duplicate.id,
                        "redundant_object_deleted": deleted,
                        "object_uri": None if deleted else durable_uri,
                        "content_sha256": content_sha256,
                    },
                    worker_id=worker_id,
                )

            store = get_object_store()
            data = store.read_bytes(
                durable_uri,
                max_bytes=int(settings.CONNECTOR_MAX_UPLOAD_BYTES),
                tenant_id=tenant_id,
                connection_id=connection.id,
            )
            if len(data) != expected_size:
                raise RuntimeError("connector object size differs from the queued job contract")
            if hashlib.sha256(data).hexdigest() != content_sha256:
                raise RuntimeError("connector object checksum differs from the queued job contract")
            if heartbeat.lost:
                db.rollback()
                return "deferred"

            result = ingest_upload(
                db,
                tenant_id=tenant_id,
                connection=connection,
                filename=str(payload.get("filename") or "upload"),
                content_type=payload.get("content_type"),
                data=data,
            )
            if heartbeat.lost:
                db.rollback()
                return "deferred"

            source_id = (result.get("data_source") or {}).get("id")
            if source_id:
                identity_row = db.get(DataSourceIdentity, str(source_id))
                source_row = db.get(DataSource, str(source_id))
                if identity_row is not None:
                    identity_row.content_sha256 = content_sha256
                    identity_row.object_size_bytes = expected_size
                if source_row is not None:
                    transient_path = source_row.storage_path
                    source_row.storage_path = durable_uri
                    metadata = dict(source_row.metadata_json or {})
                    metadata.update({"durable_object_uri": durable_uri, "content_sha256": content_sha256})
                    source_row.metadata_json = metadata
                    _remove_transient_copy(transient_path, durable_uri)
            job = db.get(IngestionJobState, job_id)
            if job is None:
                raise RuntimeError("ingestion job disappeared during processing")
            return _complete(
                db,
                job,
                _json_safe_completion(
                    result,
                    source_id=str(source_id) if source_id else None,
                    durable_uri=durable_uri,
                    checksum=content_sha256,
                ),
                worker_id=worker_id,
            )
        except Exception as exc:
            return _fail_or_retry(db, job_id, exc, worker_id=worker_id)

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.models.task_outbox import TaskOutbox
from app.services.object_storage import S3ObjectStore, StoredObject


TASK_TYPE = "connector_ingest_object"


def idempotency_key(tenant_id: str, connection_id: str, checksum: str) -> str:
    return hashlib.sha256(f"{tenant_id}|{connection_id}|{checksum}".encode("utf-8")).hexdigest()


def stage_durable_object_job(
    db: Session,
    *,
    store: S3ObjectStore,
    stored: StoredObject,
    tenant_id: str,
    connection: ConnectorConnection,
    filename: str,
    content_type: str | None,
) -> tuple[IngestionJob, bool]:
    """Persist one idempotent queued job plus its transactional outbox row.

    The caller has already uploaded ``stored``. This function owns cleanup of
    that newly-created object until the job/outbox transaction commits.
    """
    if connection.tenant_id != tenant_id:
        store.delete(stored.uri)
        raise ValueError("connector ingestion ownership mismatch")

    key = idempotency_key(tenant_id, connection.id, stored.sha256)
    existing = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == tenant_id,
        IngestionJob.idempotency_key == key,
    ).first()
    if existing is not None:
        store.delete(stored.uri)
        return existing, True

    now = datetime.utcnow()
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=TASK_TYPE,
        status="queued",
        input_json={
            "object_uri": stored.uri,
            "filename": filename,
            "content_type": content_type,
            "content_sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "connection_id": connection.id,
        },
        output_json={},
        idempotency_key=key,
        attempt_count=0,
        max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(job)
        db.flush()
        db.add(
            TaskOutbox(
                job_id=job.id,
                tenant_id=tenant_id,
                task_type=TASK_TYPE,
                payload_json={"job_id": job.id},
                status="pending",
                publish_attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        db.refresh(job)
        return job, False
    except IntegrityError:
        db.rollback()
        existing = db.query(IngestionJob).filter(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.idempotency_key == key,
        ).first()
        store.delete(stored.uri)
        if existing is not None:
            return existing, True
        raise
    except Exception:
        db.rollback()
        try:
            store.delete(stored.uri)
        finally:
            raise

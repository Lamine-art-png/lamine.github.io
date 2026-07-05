from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.hardened_records import IngestionJobState
from app.models.operational_records import ConnectorConnection
from app.models.task_outbox import TaskOutbox
from app.services.ingestion_stream import StreamedUpload
from app.services.object_storage import StoredObject, get_object_store


TASK_TYPE = "connector_ingest_object"


def _identity(tenant_id: str, connection_id: str, content_sha256: str) -> str:
    return hashlib.sha256(f"{tenant_id}|{connection_id}|{content_sha256}".encode("utf-8")).hexdigest()


def stage_streamed_ingestion(
    db: Session,
    *,
    tenant_id: str,
    connection: ConnectorConnection,
    receipt: StreamedUpload,
) -> tuple[IngestionJobState, StoredObject, bool]:
    if connection.tenant_id != tenant_id:
        raise ValueError("connector ingestion ownership mismatch")
    store = get_object_store()
    stored = store.put_path(
        receipt.path,
        tenant_id=tenant_id,
        connection_id=connection.id,
        filename=receipt.filename,
        content_type=receipt.content_type,
        expected_sha256=receipt.sha256,
        expected_size=receipt.size_bytes,
    )
    key = _identity(tenant_id, connection.id, receipt.sha256)
    existing = db.query(IngestionJobState).filter(
        IngestionJobState.tenant_id == tenant_id,
        IngestionJobState.idempotency_key == key,
    ).first()
    if existing is not None:
        store.delete(stored.uri)
        return existing, stored, True

    now = datetime.utcnow()
    job = IngestionJobState(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=TASK_TYPE,
        status="queued",
        input_json={
            "object_uri": stored.uri,
            "filename": receipt.filename,
            "content_type": receipt.content_type,
            "content_sha256": receipt.sha256,
            "size_bytes": receipt.size_bytes,
            "connection_id": connection.id,
        },
        output_json={},
        idempotency_key=key,
        attempt_count=0,
        max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    db.add(TaskOutbox(job_id=job.id, tenant_id=tenant_id, task_type=TASK_TYPE, payload_json={"job_id": job.id}, status="pending", publish_attempts=0, created_at=now, updated_at=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(IngestionJobState).filter(
            IngestionJobState.tenant_id == tenant_id,
            IngestionJobState.idempotency_key == key,
        ).first()
        store.delete(stored.uri)
        if existing is None:
            raise
        return existing, stored, True
    db.refresh(job)
    return job, stored, False

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.models.task_outbox import TaskOutbox


TASK_TYPE = "connector_provider_sync"
SUPPORTED_PROVIDERS = {"google_drive", "outlook"}


def queue_provider_sync(db: Session, *, tenant_id: str, connection: ConnectorConnection) -> tuple[IngestionJob, bool]:
    if connection.tenant_id != tenant_id:
        raise ValueError("provider sync ownership mismatch")
    if connection.provider not in SUPPORTED_PROVIDERS:
        raise ValueError("provider does not have a production sync adapter")

    existing = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == tenant_id,
        IngestionJob.connector_connection_id == connection.id,
        IngestionJob.job_type == TASK_TYPE,
        IngestionJob.status.in_(["queued", "running", "retrying"]),
    ).order_by(IngestionJob.created_at.desc()).first()
    if existing is not None:
        return existing, True

    now = datetime.utcnow()
    request_id = uuid.uuid4().hex
    identity = hashlib.sha256(
        f"{tenant_id}|{connection.id}|{TASK_TYPE}|{request_id}".encode("utf-8")
    ).hexdigest()
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=TASK_TYPE,
        status="queued",
        input_json={"provider": connection.provider, "connection_id": connection.id},
        output_json={},
        idempotency_key=identity,
        attempt_count=0,
        max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    db.add(
        TaskOutbox(
            job_id=job.id,
            tenant_id=tenant_id,
            task_type=TASK_TYPE,
            payload_json={"job_id": job.id, "provider": connection.provider},
            status="pending",
            publish_attempts=0,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    db.refresh(job)
    return job, False

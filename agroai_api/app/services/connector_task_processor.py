from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import datetime

from app.db.base import SessionLocal
from app.models.hardened_records import IngestionJobState
from app.services.ingestion_job_runner import process_ingestion_job
from app.services.provider_sync_jobs import TASK_TYPE as PROVIDER_SYNC_TASK_TYPE
from app.services.provider_sync_runner import process_provider_sync_job


SYSTEM_QUEUE_CANARY_TASK_TYPE = "system_queue_canary"
SYSTEM_QUEUE_CANARY_TENANT_ID = "__agroai_system_queue_canary__"


def worker_identity(prefix: str = "connector-worker") -> str:
    return f"{prefix}:{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def _process_queue_canary(db, *, job_id: str, tenant_id: str, worker_id: str) -> str:
    if tenant_id != SYSTEM_QUEUE_CANARY_TENANT_ID:
        return "failed"
    job = db.get(IngestionJobState, job_id)
    if job is None or job.tenant_id != tenant_id or job.job_type != SYSTEM_QUEUE_CANARY_TASK_TYPE:
        return "retrying"
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    now = datetime.utcnow()
    job.status = "succeeded"
    job.worker_id = worker_id
    job.output_json = {
        "canary": True,
        "transport": "durable_connector_queue",
        "completed_at": now.isoformat() + "Z",
    }
    job.error = None
    job.completed_at = now
    job.lease_expires_at = None
    job.updated_at = now
    db.commit()
    return "succeeded"


def process_connector_task(
    *,
    job_id: str,
    tenant_id: str,
    task_type: str,
    worker_id: str | None = None,
) -> str:
    """Execute one persisted connector task against the authoritative database.

    Transport is deliberately outside this function. Redis-compatible workers,
    Cloudflare Queue delivery, and focused tests all use the same processing
    boundary so transport changes cannot fork business semantics.
    """
    resolved_worker_id = worker_id or worker_identity()
    db = SessionLocal()
    try:
        if task_type == SYSTEM_QUEUE_CANARY_TASK_TYPE:
            return _process_queue_canary(
                db,
                job_id=job_id,
                tenant_id=tenant_id,
                worker_id=resolved_worker_id,
            )
        if task_type == PROVIDER_SYNC_TASK_TYPE:
            return asyncio.run(
                process_provider_sync_job(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    worker_id=resolved_worker_id,
                )
            )
        return process_ingestion_job(
            db,
            job_id=job_id,
            tenant_id=tenant_id,
            worker_id=resolved_worker_id,
        )
    finally:
        db.close()

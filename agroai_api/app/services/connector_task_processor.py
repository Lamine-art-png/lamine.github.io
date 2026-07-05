from __future__ import annotations

import asyncio
import socket
import uuid

from app.db.base import SessionLocal
from app.services.ingestion_job_runner import process_ingestion_job
from app.services.provider_sync_jobs import TASK_TYPE as PROVIDER_SYNC_TASK_TYPE
from app.services.provider_sync_runner import process_provider_sync_job


def worker_identity(prefix: str = "connector-worker") -> str:
    return f"{prefix}:{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def process_connector_task(
    *,
    job_id: str,
    tenant_id: str,
    task_type: str,
    worker_id: str | None = None,
) -> str:
    resolved_worker_id = worker_id or worker_identity()
    db = SessionLocal()
    try:
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

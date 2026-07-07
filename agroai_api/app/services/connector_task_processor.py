from __future__ import annotations

import asyncio
import socket
import uuid

from app.db.base import SessionLocal
from app.models.operational_records import IngestionJob
from app.services.ag_connector_runtime import AG_PROVIDERS
from app.services.ag_provider_worker import process_ag_provider_job
from app.services.durable_ingestion_staging import TASK_TYPE as INGESTION_TASK_TYPE
from app.services.ingestion_job_runner import process_ingestion_job
from app.services.provider_sync_jobs import TASK_TYPE as PROVIDER_SYNC_TASK_TYPE
from app.services.provider_sync_runner import process_provider_sync_job


SUPPORTED_TASK_TYPES = frozenset({INGESTION_TASK_TYPE, PROVIDER_SYNC_TASK_TYPE})


def worker_identity(prefix: str = "connector-worker") -> str:
    return f"{prefix}:{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def process_connector_task(
    *,
    job_id: str,
    tenant_id: str,
    task_type: str,
    worker_id: str | None = None,
) -> str:
    if task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError("unsupported connector task type")

    resolved_worker_id = worker_id or worker_identity()
    db = SessionLocal()
    try:
        if task_type == PROVIDER_SYNC_TASK_TYPE:
            job = db.get(IngestionJob, job_id)
            provider = str((job.input_json or {}).get("provider") or "") if job is not None else ""
            processor = process_ag_provider_job if provider in AG_PROVIDERS else process_provider_sync_job
            return asyncio.run(
                processor(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    worker_id=resolved_worker_id,
                )
            )
        if task_type == INGESTION_TASK_TYPE:
            return process_ingestion_job(
                db,
                job_id=job_id,
                tenant_id=tenant_id,
                worker_id=resolved_worker_id,
            )
        raise AssertionError("validated connector task type lost dispatch coverage")
    finally:
        db.close()

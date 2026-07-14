from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import connector_mode
from app.api.v1.connectors import create_or_get_connection
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.services.connector_ingestion_pipeline import ingest_streamed_receipt
from app.services.durable_ingestion_staging import stage_durable_object_job
from app.services.ingestion_stream import stream_upload_to_spool
from app.services.object_storage import object_storage_configured
from app.services.redis_task_queue import queue_configured


logger = logging.getLogger(__name__)
router = APIRouter(tags=["connector-stream-ingestion"])
_ALLOWED_PROVIDERS = {
    "wiseconn", "talgil", "universal_controller", "weather", "openet",
    "manual_csv", "chat_upload",
}


def _object_store():
    from app.api.v1.connector_stream_api import get_object_store
    return get_object_store()


def _publish_pending(*, limit: int):
    from app.api.v1.connector_stream_api import drain_pending_outbox
    return drain_pending_outbox(limit=limit)


async def _inline_processing_fallback(job_id: str, tenant_id: str) -> None:
    """Give every durably staged job a delayed second execution path.

    The external queue remains primary. After a short grace period this path checks
    the same lease-fenced, idempotent job. It becomes a no-op when the queue already
    completed or claimed the job, and it processes the file when queue delivery is
    delayed or broken.
    """
    await asyncio.sleep(8)
    from app.services.connector_task_processor import process_connector_task
    from app.services.durable_ingestion_staging import TASK_TYPE

    try:
        await asyncio.to_thread(
            process_connector_task,
            job_id=job_id,
            tenant_id=tenant_id,
            task_type=TASK_TYPE,
            worker_id=f"upload-fallback:{job_id[:16]}",
        )
    except Exception:
        logger.exception("upload processing fallback failed job_id=%s tenant_id=%s", job_id, tenant_id)


@router.post("/evidence/upload-stream")
async def upload_stream_secure(
    background_tasks: BackgroundTasks,
    provider: str = Query(default="manual_csv"),
    workspace_id: str | None = Query(default=None),
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if provider not in _ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider does not support streamed evidence upload")

    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=provider,
        workspace_id=workspace_id,
        mode=connector_mode(provider),
        config={"created_by": "bounded_stream_upload"},
    )
    db.commit()
    db.refresh(connection)

    receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
    durable = object_storage_configured()
    queued = queue_configured()
    if durable != queued:
        Path(receipt.path).unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail={
            "error": "distributed_ingestion_misconfigured",
            "message": "Durable object storage and the external task queue must be configured together.",
        })

    if durable and queued:
        store = _object_store()
        try:
            stored = await asyncio.to_thread(
                store.put_path,
                receipt.path,
                tenant_id=tenant_id,
                connection_id=connection.id,
                filename=receipt.filename,
                content_type=receipt.content_type,
                expected_sha256=receipt.sha256,
                expected_size=receipt.size_bytes,
            )
            job, deduplicated = stage_durable_object_job(
                db,
                store=store,
                stored=stored,
                tenant_id=tenant_id,
                connection=connection,
                filename=receipt.filename,
                content_type=receipt.content_type,
            )

            # Drain after every receipt, including a deduplicated retry. Previously a
            # failed first publication could leave the durable job queued forever,
            # because the retry found the same job and skipped publishing its outbox.
            publication = await asyncio.to_thread(_publish_pending, limit=50)
            failed = int(publication.get("failed", 0) or 0)
            processing_pending = job.status in {"queued", "retrying", "running"}
            fallback_scheduled = processing_pending
            if fallback_scheduled:
                background_tasks.add_task(_inline_processing_fallback, job.id, tenant_id)

            warnings = []
            if failed > 0:
                warnings.append(
                    "External queue delivery is delayed. The file is durable and AGRO-AI scheduled an automatic processing fallback."
                )

            return {
                "status": job.status,
                "phase": "stored" if processing_pending else job.status,
                "durable_stored": True,
                "processing_pending": processing_pending,
                "job_id": job.id,
                "content_sha256": receipt.sha256,
                "size_bytes": receipt.size_bytes,
                "deduplicated": deduplicated,
                "queue_publication": publication,
                "processing_fallback_scheduled": fallback_scheduled,
                "warnings": warnings,
                "message": "File securely stored and queued for AGRO-AI processing.",
            }
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail={
                "error": "durable_ingestion_stage_failed",
                "message": "AGRO-AI could not securely store and stage this file. Retry the upload.",
                "provider": provider,
                "receipt_sha256": receipt.sha256,
            }) from exc
        finally:
            Path(receipt.path).unlink(missing_ok=True)

    try:
        return await asyncio.to_thread(
            ingest_streamed_receipt,
            tenant_id=tenant_id,
            connection_id=connection.id,
            receipt=receipt,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail={
            "error": "stream_ingestion_failed",
            "message": "AGRO-AI received the file but could not finish processing it. Retry the upload.",
            "provider": provider,
            "receipt_sha256": receipt.sha256,
        }) from exc

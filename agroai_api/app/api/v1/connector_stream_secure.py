from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
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


@router.post("/evidence/upload-stream")
async def upload_stream_secure(
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
            publication = {"published": 0, "failed": 0}
            if not deduplicated:
                publication = await asyncio.to_thread(_publish_pending, limit=10)
            return {
                "status": job.status,
                "phase": "stored" if job.status in {"queued", "retrying", "running"} else job.status,
                "durable_stored": True,
                "processing_pending": job.status in {"queued", "retrying", "running"},
                "job_id": job.id,
                "content_sha256": receipt.sha256,
                "size_bytes": receipt.size_bytes,
                "deduplicated": deduplicated,
                "queue_publication": publication,
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

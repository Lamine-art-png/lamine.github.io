from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import ingest_upload
from app.api.v1.connectors import public_connection
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.services.durable_ingestion_staging import stage_durable_object_job
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.object_storage import get_object_store, object_storage_configured
from app.services.redis_task_queue import queue_configured
from app.services.task_outbox_service import drain_pending_outbox


router = APIRouter(tags=["connector-stream-ingestion"])


def _connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


@router.post("/connectors/connections/{connection_id}/upload-stream")
async def upload_connection_stream(
    connection_id: str,
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    connection = _connection(db, tenant_id, connection_id)
    receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
    durable = object_storage_configured()
    queued = queue_configured()
    if durable != queued:
        Path(receipt.path).unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail={"error": "distributed_ingestion_misconfigured"})

    if durable and queued:
        store = get_object_store()
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
                publication = await asyncio.to_thread(drain_pending_outbox, limit=10)
            return {
                "status": job.status,
                "connection": public_connection(connection),
                "job_id": job.id,
                "object_uri": None if deduplicated else stored.uri,
                "content_sha256": receipt.sha256,
                "size_bytes": receipt.size_bytes,
                "deduplicated": deduplicated,
                "queue_publication": publication,
            }
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail={"error": "durable_connection_upload_stage_failed", "reason": exc.__class__.__name__},
            ) from exc
        finally:
            Path(receipt.path).unlink(missing_ok=True)

    try:
        data = read_spooled_bytes(receipt)
        return ingest_upload(
            db,
            tenant_id=tenant_id,
            connection=connection,
            filename=receipt.filename,
            content_type=receipt.content_type,
            data=data,
        )
    finally:
        Path(receipt.path).unlink(missing_ok=True)

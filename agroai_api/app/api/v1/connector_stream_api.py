from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import connector_mode
from app.api.v1.connectors import create_or_get_connection
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.hardened_records import IngestionJobState
from app.models.task_outbox import TaskOutbox
from app.services.connector_ingestion_pipeline import ingest_streamed_receipt
from app.services.ingestion_stream import stream_upload_to_spool
from app.services.object_storage import get_object_store, object_storage_configured
from app.services.redis_task_queue import queue_configured
from app.services.task_outbox_service import publish_pending_outbox


router = APIRouter(tags=["connector-stream-ingestion"])
_ALLOWED_PROVIDERS = {
    "wiseconn", "talgil", "universal_controller", "weather", "openet",
    "manual_csv", "chat_upload",
}
_TASK_TYPE = "connector_ingest_object"


def _idempotency_key(tenant_id: str, connection_id: str, checksum: str) -> str:
    return hashlib.sha256(f"{tenant_id}|{connection_id}|{checksum}".encode("utf-8")).hexdigest()


@router.post("/evidence/upload-stream")
async def upload_stream(
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
        raise HTTPException(status_code=503, detail={"error": "distributed_ingestion_misconfigured", "message": "Durable object storage and the external task queue must be configured together."})

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
            key = _idempotency_key(tenant_id, connection.id, receipt.sha256)
            existing = db.query(IngestionJobState).filter(
                IngestionJobState.tenant_id == tenant_id,
                IngestionJobState.idempotency_key == key,
            ).first()
            if existing is not None:
                await asyncio.to_thread(store.delete, stored.uri)
                return {"status": existing.status, "job_id": existing.id, "deduplicated": True, "content_sha256": receipt.sha256}

            now = datetime.utcnow()
            job = IngestionJobState(
                tenant_id=tenant_id,
                workspace_id=connection.workspace_id,
                connector_connection_id=connection.id,
                job_type=_TASK_TYPE,
                status="queued",
                input_json={"object_uri": stored.uri, "filename": receipt.filename, "content_type": receipt.content_type, "content_sha256": receipt.sha256, "size_bytes": receipt.size_bytes, "connection_id": connection.id},
                output_json={},
                idempotency_key=key,
                attempt_count=0,
                max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
                created_at=now,
                updated_at=now,
            )
            db.add(job)
            db.flush()
            db.add(TaskOutbox(job_id=job.id, tenant_id=tenant_id, task_type=_TASK_TYPE, payload_json={"job_id": job.id}, status="pending", publish_attempts=0, created_at=now, updated_at=now))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                await asyncio.to_thread(store.delete, stored.uri)
                existing = db.query(IngestionJobState).filter(IngestionJobState.tenant_id == tenant_id, IngestionJobState.idempotency_key == key).first()
                if existing is None:
                    raise
                return {"status": existing.status, "job_id": existing.id, "deduplicated": True, "content_sha256": receipt.sha256}
            db.refresh(job)
            publication = await asyncio.to_thread(publish_pending_outbox, db, limit=10)
            return {
                "status": "queued",
                "job_id": job.id,
                "object_uri": stored.uri,
                "content_sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
                "deduplicated": False,
                "queue_publication": publication,
            }
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail={"error": "durable_ingestion_stage_failed", "provider": provider, "receipt_sha256": receipt.sha256}) from exc
        finally:
            Path(receipt.path).unlink(missing_ok=True)

    try:
        return await asyncio.to_thread(ingest_streamed_receipt, tenant_id=tenant_id, connection_id=connection.id, receipt=receipt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "stream_ingestion_failed", "provider": provider, "receipt_sha256": receipt.sha256}) from exc


# Internal queue callbacks share the same connector task surface and are mounted
# under the application's existing /v1 connector router prefix.
from app.api.v1.cloudflare_queue import router as cloudflare_queue_router  # noqa: E402

router.include_router(cloudflare_queue_router)

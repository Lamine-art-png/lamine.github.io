from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import connector_mode
from app.api.v1.connectors import create_or_get_connection
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, QuotaReservation
from app.services.connector_ingestion_pipeline import ingest_streamed_receipt
from app.services.durable_ingestion_staging import stage_durable_object_job
from app.services.ingestion_stream import stream_upload_to_spool
from app.services.object_storage import object_storage_configured
from app.services.quota import commit_reservation, release_reservation, reserve_quota
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


def _release_reserved(db: Session, reservation_id: str, reason: str) -> None:
    row = db.get(QuotaReservation, reservation_id)
    if row is not None and row.state == "reserved":
        release_reservation(db, row, reason=reason)
        db.commit()


def _commit_import(db: Session, reservation_id: str, *, provider: str, connection_id: str, surface: str) -> None:
    row = db.get(QuotaReservation, reservation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "quota_reservation_missing", "message": "Import accounting could not be finalized."},
        )
    commit_reservation(
        db,
        row,
        event_type="evidence_upload",
        metadata={"provider": provider, "connection_id": connection_id, "surface": surface},
    )
    db.commit()


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

    org = db.get(Organization, tenant_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

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

    reservation = reserve_quota(
        db,
        org,
        "evidence_upload",
        workspace_id=workspace_id,
        metadata={
            "provider": provider,
            "connection_id": connection.id,
            "filename": file.filename or "upload",
            "surface": "evidence_upload_stream",
        },
    )
    reservation_id = reservation.id
    receipt = None

    try:
        receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
        durable = object_storage_configured()
        queued = queue_configured()
        if durable != queued:
            _release_reserved(db, reservation_id, "distributed_ingestion_misconfigured")
            raise HTTPException(status_code=503, detail={
                "error": "distributed_ingestion_misconfigured",
                "message": "Durable object storage and the external task queue must be configured together.",
            })

        if durable and queued:
            store = _object_store()
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
            if deduplicated:
                _release_reserved(db, reservation_id, "deduplicated_import")
            else:
                _commit_import(
                    db,
                    reservation_id,
                    provider=provider,
                    connection_id=connection.id,
                    surface="durable_evidence_upload_stream",
                )
                publication = await asyncio.to_thread(_publish_pending, limit=10)
            return {
                "status": job.status,
                "job_id": job.id,
                "object_uri": None if deduplicated else stored.uri,
                "content_sha256": receipt.sha256,
                "size_bytes": receipt.size_bytes,
                "deduplicated": deduplicated,
                "queue_publication": publication,
                "commercial_metric": "evidence_upload",
                "shared_import_quota": True,
            }

        result = await asyncio.to_thread(
            ingest_streamed_receipt,
            tenant_id=tenant_id,
            connection_id=connection.id,
            receipt=receipt,
        )
        _commit_import(
            db,
            reservation_id,
            provider=provider,
            connection_id=connection.id,
            surface="synchronous_evidence_upload_stream",
        )
        return {**result, "commercial_metric": "evidence_upload", "shared_import_quota": True}
    except HTTPException:
        db.rollback()
        _release_reserved(db, reservation_id, "stream_upload_http_error")
        raise
    except Exception as exc:
        db.rollback()
        _release_reserved(db, reservation_id, "stream_upload_failed")
        raise HTTPException(status_code=500, detail={
            "error": "stream_ingestion_failed",
            "provider": provider,
            "receipt_sha256": receipt.sha256 if receipt is not None else None,
        }) from exc
    finally:
        if receipt is not None:
            Path(receipt.path).unlink(missing_ok=True)

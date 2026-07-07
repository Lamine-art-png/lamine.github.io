from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import ingest_upload
from app.api.v1.connectors import public_connection
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, QuotaReservation
from app.services.durable_ingestion_staging import stage_durable_object_job
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.object_storage import get_object_store, object_storage_configured
from app.services.quota import commit_reservation, release_reservation, reserve_quota
from app.services.redis_task_queue import queue_configured
from app.services.task_outbox_service import drain_pending_outbox

router = APIRouter(tags=["connector-stream-ingestion"])


def _connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


def _release_reserved(db: Session, reservation_id: str, reason: str) -> None:
    row = db.get(QuotaReservation, reservation_id)
    if row is not None and row.state == "reserved":
        release_reservation(db, row, reason=reason)
        db.commit()


def _commit_import(db: Session, reservation_id: str, *, connection: ConnectorConnection, surface: str) -> None:
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
        metadata={"provider": connection.provider, "connection_id": connection.id, "surface": surface},
    )
    db.commit()


@router.post("/connectors/connections/{connection_id}/upload")
@router.post("/connectors/connections/{connection_id}/upload-stream")
async def upload_connection_stream(
    connection_id: str,
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    connection = _connection(db, tenant_id, connection_id)
    org = db.get(Organization, tenant_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    reservation = reserve_quota(
        db,
        org,
        "evidence_upload",
        workspace_id=connection.workspace_id,
        metadata={
            "provider": connection.provider,
            "connection_id": connection.id,
            "filename": file.filename or "upload",
            "surface": "connection_upload",
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
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "distributed_ingestion_misconfigured",
                    "message": "Durable object storage and the external task queue must be configured together.",
                },
            )

        if durable and queued:
            store = get_object_store()
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
                _commit_import(db, reservation_id, connection=connection, surface="durable_connection_upload")
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
                "commercial_metric": "evidence_upload",
                "shared_import_quota": True,
            }

        data = read_spooled_bytes(receipt)
        result = ingest_upload(
            db,
            tenant_id=tenant_id,
            connection=connection,
            filename=receipt.filename,
            content_type=receipt.content_type,
            data=data,
        )
        _commit_import(db, reservation_id, connection=connection, surface="synchronous_connection_upload")
        return {**result, "commercial_metric": "evidence_upload", "shared_import_quota": True}
    except HTTPException:
        db.rollback()
        _release_reserved(db, reservation_id, "connection_upload_http_error")
        raise
    except Exception as exc:
        db.rollback()
        _release_reserved(db, reservation_id, "connection_upload_failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "connection_upload_ingestion_failed", "reason": exc.__class__.__name__},
        ) from exc
    finally:
        if receipt is not None:
            Path(receipt.path).unlink(missing_ok=True)

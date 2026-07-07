from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import ProviderId, ingest_upload
from app.api.v1.connectors import create_or_get_connection, verify_connector_schema
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, QuotaReservation
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.quota import commit_reservation, quota_snapshot, release_reservation, reserve_quota

router = APIRouter(tags=["connector-hub-actions"])


def _release(db: Session, reservation_id: str, reason: str) -> None:
    row = db.get(QuotaReservation, reservation_id)
    if row is not None and row.state == "reserved":
        release_reservation(db, row, reason=reason)
        db.commit()


@router.post("/evidence/upload")
async def upload_commercial_evidence_file(
    provider: ProviderId = Query(default="manual_csv"),
    workspace_id: str | None = Query(default=None),
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    verify_connector_schema(db)
    org = db.get(Organization, tenant_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    mode = "manual_upload" if provider in {"manual_csv", "chat_upload"} else "export_upload"
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=provider,
        workspace_id=workspace_id,
        mode=mode,
        config={"created_by": "commercial_evidence_upload"},
    )
    reservation = reserve_quota(
        db,
        org,
        "evidence_upload",
        workspace_id=workspace_id,
        metadata={"provider": provider, "filename": file.filename or "upload"},
    )
    reservation_id = reservation.id
    receipt = None
    try:
        receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
        result = ingest_upload(
            db,
            tenant_id=tenant_id,
            connection=connection,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=read_spooled_bytes(receipt),
        )
        row = db.get(QuotaReservation, reservation_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "quota_reservation_missing", "message": "Import accounting could not be finalized."},
            )
        commit_reservation(db, row, event_type="evidence_upload", metadata={"provider": provider})
        db.commit()
        usage = quota_snapshot(db, org, ["evidence_upload"])["metrics"]["evidence_upload"]
        return {**result, "commercial_usage": usage, "commercial_metric": "evidence_upload", "shared_import_quota": True}
    except HTTPException:
        db.rollback()
        _release(db, reservation_id, "upload_http_error")
        raise
    except Exception as exc:
        db.rollback()
        _release(db, reservation_id, "upload_ingestion_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "upload_ingestion_failed", "message": "The file could not be imported."},
        ) from exc
    finally:
        if receipt is not None:
            Path(receipt.path).unlink(missing_ok=True)

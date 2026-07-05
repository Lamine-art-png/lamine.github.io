from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.connector_hub import connector_mode
from app.api.v1.connectors import create_or_get_connection
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.services.connector_ingestion_pipeline import ingest_streamed_receipt
from app.services.ingestion_stream import stream_upload_to_spool


router = APIRouter(tags=["connector-stream-ingestion"])
_ALLOWED_PROVIDERS = {
    "wiseconn", "talgil", "universal_controller", "weather", "openet",
    "manual_csv", "chat_upload",
}


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

    receipt = await stream_upload_to_spool(
        file,
        tenant_id=tenant_id,
        connection_id=connection.id,
    )
    try:
        return await asyncio.to_thread(
            ingest_streamed_receipt,
            tenant_id=tenant_id,
            connection_id=connection.id,
            receipt=receipt,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "stream_ingestion_failed",
                "provider": provider,
                "receipt_sha256": receipt.sha256,
            },
        ) from exc

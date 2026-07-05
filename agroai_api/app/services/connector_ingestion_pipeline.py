from __future__ import annotations

from pathlib import Path
from typing import Any

from app.api.v1.connector_hub import ingest_upload
from app.db.base import SessionLocal
from app.models.operational_records import ConnectorConnection
from app.services.ingestion_stream import StreamedUpload, read_spooled_bytes


def ingest_streamed_receipt(
    *,
    tenant_id: str,
    connection_id: str,
    receipt: StreamedUpload,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Process one bounded upload using a worker-owned database session.

    This function is intentionally synchronous and independent of FastAPI so it
    can run in ``asyncio.to_thread`` today and an external task worker later
    without crossing a request-bound SQLAlchemy session between threads.
    """
    db = SessionLocal()
    try:
        connection = db.get(ConnectorConnection, connection_id)
        if not connection or connection.tenant_id != tenant_id:
            raise RuntimeError("connector connection is unavailable for ingestion")

        data = read_spooled_bytes(receipt)
        result = ingest_upload(
            db,
            tenant_id=tenant_id,
            connection=connection,
            filename=receipt.filename,
            content_type=receipt.content_type,
            data=data,
        )
        result["upload_receipt"] = {
            "size_bytes": receipt.size_bytes,
            "sha256": receipt.sha256,
            "streamed": True,
        }
        return result
    finally:
        db.close()
        if cleanup:
            Path(receipt.path).unlink(missing_ok=True)

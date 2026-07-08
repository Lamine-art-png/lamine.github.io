from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import IngestionJob
from app.services.object_storage import get_object_store
from app.services.task_outbox_service import drain_pending_outbox


# Compatibility module retained for imports used by the hardened streamed-upload
# route. Public upload handling lives only in connector_stream_secure.py; keeping
# a second /evidence/upload-stream route here made route order determine behavior.
router = APIRouter(tags=["connector-stream-internal"])


@router.get("/connectors/jobs/{job_id}")
def connector_ingestion_job_status(
    job_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return a tenant-scoped, customer-safe ingestion receipt.

    The durable upload route is intentionally asynchronous in production. This
    endpoint lets the portal follow the exact job it just created without
    exposing object-store URIs, queue internals, or another tenant's job.
    """
    job = db.get(IngestionJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    output = dict(job.output_json or {})
    return {
        "job": {
            "id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "connection_id": job.connector_connection_id,
            "data_source_id": output.get("data_source_id") or job.data_source_id,
            "rows_parsed": int(output.get("rows_parsed") or 0),
            "evidence_records_created": int(output.get("evidence_records_created") or 0),
            "deduplicated": bool(output.get("deduplicated", False)),
            "warning_count": int(output.get("warning_count") or 0),
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    }


# Internal Queue callbacks are intentionally mounted on this compatibility router
# so app.main can preserve its existing include boundary.
from app.api.v1.cloudflare_queue import router as cloudflare_queue_router  # noqa: E402

router.include_router(cloudflare_queue_router)


__all__ = ["router", "get_object_store", "drain_pending_outbox"]

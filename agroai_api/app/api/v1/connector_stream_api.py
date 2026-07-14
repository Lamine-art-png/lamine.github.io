from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import DataSource, IngestionJob
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
    """Return a tenant-scoped, customer-safe ingestion receipt."""
    job = db.get(IngestionJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    output = dict(job.output_json or {})
    source_id = str(output.get("data_source_id") or job.data_source_id or "") or None
    source = db.get(DataSource, source_id) if source_id else None
    if source is not None and source.tenant_id != tenant_id:
        source = None

    return {
        "job": {
            "id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "connection_id": job.connector_connection_id,
            "data_source_id": source_id,
            "source_visible": bool(source),
            "filename": source.filename if source is not None else (job.input_json or {}).get("filename"),
            "source_status": source.status if source is not None else None,
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


# Internal Queue callbacks and customer source-library routes are mounted on this
# compatibility router so app.main preserves its existing include boundary.
from app.api.v1.cloudflare_queue import router as cloudflare_queue_router  # noqa: E402
from app.api.v1.source_library import router as source_library_router  # noqa: E402
from app.api.v1.source_library_delete import router as source_library_delete_router  # noqa: E402

router.include_router(cloudflare_queue_router)
router.include_router(source_library_router)
router.include_router(source_library_delete_router)


__all__ = ["router", "get_object_store", "drain_pending_outbox"]

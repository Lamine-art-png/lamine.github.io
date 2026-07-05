from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.hardened_records import IngestionJobState
from app.models.operational_records import DataSource
from app.services.connector_object_retention import gc_candidate
from app.services.object_storage import get_object_store


def collect_expired_connector_objects(db: Session, limit: int | None = None) -> dict[str, int]:
    days = max(1, int(getattr(settings, "CONNECTOR_FAILED_OBJECT_RETENTION_DAYS", 7) or 7))
    batch = max(1, min(int(limit or getattr(settings, "CONNECTOR_OBJECT_GC_BATCH_SIZE", 50) or 50), 200))
    cutoff = datetime.utcnow() - timedelta(days=days)
    jobs = (
        db.query(IngestionJobState)
        .filter(
            IngestionJobState.job_type == "connector_ingest_object",
            IngestionJobState.completed_at.is_not(None),
            IngestionJobState.completed_at <= cutoff,
            IngestionJobState.status.in_(["failed", "cancelled", "succeeded"]),
        )
        .order_by(IngestionJobState.completed_at.asc())
        .limit(batch)
        .all()
    )
    store = get_object_store()
    counts = {"deleted": 0, "referenced": 0, "failed": 0, "scanned": len(jobs)}
    for job in jobs:
        candidate = gc_candidate(job)
        if candidate is None:
            continue
        uri, reason = candidate
        connection_id = str(job.connector_connection_id or (job.input_json or {}).get("connection_id") or "")
        if not connection_id:
            counts["failed"] += 1
            continue
        if db.query(DataSource.id).filter(DataSource.tenant_id == job.tenant_id, DataSource.storage_path == uri).first():
            counts["referenced"] += 1
            continue
        try:
            store.delete(uri, tenant_id=job.tenant_id, connection_id=connection_id)
        except Exception:
            counts["failed"] += 1
            continue
        stamp = datetime.utcnow().isoformat()
        if reason == "terminal_job":
            payload = dict(job.input_json or {})
            payload.pop("object_uri", None)
            payload["object_gc"] = {"deleted_at": stamp, "reason": reason}
            job.input_json = payload
        else:
            output = dict(job.output_json or {})
            output["object_uri"] = None
            output["redundant_object_deleted"] = True
            output["object_gc"] = {"deleted_at": stamp, "reason": reason}
            job.output_json = output
        job.updated_at = datetime.utcnow()
        counts["deleted"] += 1
    db.commit()
    return counts

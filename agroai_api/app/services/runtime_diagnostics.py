from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.hardened_records import IngestionJobState
from app.models.task_outbox import TaskOutbox
from app.services.release_contract import evaluate_release_contract


def connector_runtime_diagnostics(db: Session) -> dict:
    now = datetime.utcnow()
    outbox_counts = {
        str(status): int(count)
        for status, count in db.query(TaskOutbox.status, func.count(TaskOutbox.id)).group_by(TaskOutbox.status).all()
    }
    job_counts = {
        str(status): int(count)
        for status, count in db.query(IngestionJobState.status, func.count(IngestionJobState.id)).group_by(IngestionJobState.status).all()
    }
    stale_leases = int(
        db.query(func.count(IngestionJobState.id))
        .filter(
            IngestionJobState.status == "running",
            IngestionJobState.lease_expires_at.is_not(None),
            IngestionJobState.lease_expires_at <= now,
        )
        .scalar()
        or 0
    )
    due_retries = int(
        db.query(func.count(IngestionJobState.id))
        .filter(
            IngestionJobState.status == "retrying",
            IngestionJobState.next_attempt_at.is_not(None),
            IngestionJobState.next_attempt_at <= now,
        )
        .scalar()
        or 0
    )
    return {
        "status": "ok",
        "checked_at": now.isoformat() + "Z",
        "outbox": outbox_counts,
        "jobs": job_counts,
        "stale_running_leases": stale_leases,
        "due_retries": due_retries,
        "release": evaluate_release_contract(db),
    }

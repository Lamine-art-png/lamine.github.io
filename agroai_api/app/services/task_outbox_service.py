from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.task_outbox import TaskOutbox
from app.services.redis_task_queue import get_task_publisher


def publish_pending_outbox(db: Session, *, limit: int = 50) -> dict[str, int]:
    now = datetime.utcnow()
    rows = (
        db.query(TaskOutbox)
        .filter(
            TaskOutbox.status == "pending",
            or_(TaskOutbox.next_attempt_at.is_(None), TaskOutbox.next_attempt_at <= now),
        )
        .order_by(TaskOutbox.created_at.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    if not rows:
        return {"published": 0, "failed": 0}
    queue = get_task_publisher()
    published = 0
    failed = 0
    for row in rows:
        try:
            queue.enqueue(row.job_id, row.tenant_id, row.task_type)
            row.status = "published"
            row.published_at = datetime.utcnow()
            row.last_error = None
            published += 1
        except Exception as exc:
            row.publish_attempts += 1
            row.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(300, 2 ** min(row.publish_attempts, 8)))
            row.last_error = f"{exc.__class__.__name__}: {str(exc)[:500]}"
            failed += 1
        row.updated_at = datetime.utcnow()
    db.commit()
    return {"published": published, "failed": failed}


def drain_pending_outbox(*, limit: int = 50) -> dict[str, int]:
    """Drain pending rows in a thread-owned database session.

    Async routes call this through ``asyncio.to_thread``. Opening the session
    here prevents a request-scoped SQLAlchemy Session from crossing thread
    boundaries while queue publication performs blocking network I/O.
    """
    db = SessionLocal()
    try:
        return publish_pending_outbox(db, limit=limit)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

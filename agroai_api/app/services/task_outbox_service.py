from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.task_outbox import TaskOutbox
from app.services.redis_task_queue import get_task_publisher


_OUTBOX_CLAIM_TIMEOUT_SECONDS = 300


def _claimable_outbox(now: datetime):
    stale_before = now - timedelta(seconds=_OUTBOX_CLAIM_TIMEOUT_SECONDS)
    return or_(
        and_(
            TaskOutbox.status == "pending",
            or_(TaskOutbox.next_attempt_at.is_(None), TaskOutbox.next_attempt_at <= now),
        ),
        and_(TaskOutbox.status == "publishing", TaskOutbox.updated_at <= stale_before),
    )


def publish_pending_outbox(db: Session, *, limit: int = 50) -> dict[str, int]:
    now = datetime.utcnow()
    rows = (
        db.query(TaskOutbox)
        .filter(_claimable_outbox(now))
        .order_by(TaskOutbox.created_at.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    if not rows:
        return {"published": 0, "failed": 0}

    queue = get_task_publisher()
    published = 0
    failed = 0
    for candidate in rows:
        claim_time = datetime.utcnow()
        claim = db.execute(
            update(TaskOutbox)
            .where(TaskOutbox.id == candidate.id, _claimable_outbox(claim_time))
            .values(status="publishing", updated_at=claim_time)
        )
        db.commit()
        if claim.rowcount != 1:
            continue

        db.refresh(candidate)
        try:
            queue.enqueue(candidate.job_id, candidate.tenant_id, candidate.task_type)
            completed_at = datetime.utcnow()
            result = db.execute(
                update(TaskOutbox)
                .where(TaskOutbox.id == candidate.id, TaskOutbox.status == "publishing")
                .values(
                    status="published",
                    published_at=completed_at,
                    next_attempt_at=None,
                    last_error=None,
                    updated_at=completed_at,
                )
            )
            db.commit()
            if result.rowcount == 1:
                published += 1
        except Exception as exc:
            db.rollback()
            db.refresh(candidate)
            attempts = int(candidate.publish_attempts or 0) + 1
            retry_at = datetime.utcnow() + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
            result = db.execute(
                update(TaskOutbox)
                .where(TaskOutbox.id == candidate.id, TaskOutbox.status == "publishing")
                .values(
                    status="pending",
                    publish_attempts=attempts,
                    next_attempt_at=retry_at,
                    last_error=f"{exc.__class__.__name__}: {str(exc)[:500]}",
                    updated_at=datetime.utcnow(),
                )
            )
            db.commit()
            if result.rowcount == 1:
                failed += 1
    return {"published": published, "failed": failed}


def drain_pending_outbox(*, limit: int = 50) -> dict[str, int]:
    """Drain publishable rows in a thread-owned database session.

    Each row is atomically moved to ``publishing`` before network I/O so
    concurrent drainers do not intentionally enqueue the same job. A crashed
    publisher leaves a recoverable stale claim; after the bounded claim timeout
    another drain may retry it. A crash after remote acceptance but before the
    local ``published`` commit can still duplicate delivery, so workers remain
    idempotent and lease-fenced by design.
    """
    db = SessionLocal()
    try:
        return publish_pending_outbox(db, limit=limit)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

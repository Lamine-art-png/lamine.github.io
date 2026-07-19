"""Always-on background worker for Field Intelligence.

Drains the durable processing and asset-deletion job queues on an interval so a
50-item batch is fully processed without any additional user traffic. Integrates
with the existing lease/heartbeat/retry semantics on ``IngestionJob`` and shuts
down cleanly. It is intentionally independent of the WiseConn sync scheduler so
field capture works even when connectors are disabled.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.db.base import SessionLocal
from app.services import field_intelligence as svc

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def drain_once() -> dict:
    """Process a bounded slice of queued jobs on a fresh session."""
    db = SessionLocal()
    try:
        batch = int(getattr(settings, "FIELD_WORKER_BATCH", 25))
        processed = svc.run_field_intelligence_jobs(db, limit=batch)
        deletions = svc.run_field_intelligence_deletions(db, limit=batch)
        orphans = svc.run_field_intelligence_orphan_cleanup(db, limit=batch)
        return {"processing": processed, "deletions": deletions, "orphan_cleanup": orphans}
    except Exception:  # noqa: BLE001 - a worker tick must never crash the loop
        db.rollback()
        logger.exception("field intelligence worker tick failed")
        return {"error": True}
    finally:
        db.close()


def drain_until_empty(db, *, max_rounds: int = 100) -> dict:
    """Process every currently-drainable job (used by tests and admin drains)."""
    total_processed = 0
    total_deleted = 0
    total_cleaned = 0
    for _ in range(max_rounds):
        proc = svc.run_field_intelligence_jobs(db, limit=50)
        dele = svc.run_field_intelligence_deletions(db, limit=50)
        orph = svc.run_field_intelligence_orphan_cleanup(db, limit=50)
        total_processed += proc.get("processed", 0)
        total_deleted += dele.get("deleted", 0)
        total_cleaned += orph.get("cleaned", 0)
        if (
            proc.get("processed", 0) == 0
            and proc.get("failed", 0) == 0
            and dele.get("deleted", 0) == 0
            and orph.get("cleaned", 0) == 0
        ):
            break
    return {"processed": total_processed, "deleted": total_deleted, "cleaned": total_cleaned}


def reconcile_once() -> dict:
    """Reconcile object-store-resident pending registrations on a fresh session."""
    db = SessionLocal()
    try:
        return svc.reconcile_pending_objects(db)
    except Exception:  # noqa: BLE001 - a reconciler tick must never crash the loop
        db.rollback()
        logger.exception("field intelligence pending-object reconciliation tick failed")
        return {"error": True}
    finally:
        db.close()


def start_field_intelligence_worker() -> AsyncIOScheduler | None:
    global _scheduler
    if not bool(getattr(settings, "FIELD_INTELLIGENCE_WORKER_ENABLED", True)):
        logger.info("Field Intelligence worker disabled by configuration")
        return None
    if _scheduler is not None:
        return _scheduler
    interval = int(getattr(settings, "FIELD_WORKER_INTERVAL_SECONDS", 15))
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        drain_once,
        trigger=IntervalTrigger(seconds=interval),
        id="field_intelligence_drain",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    reconcile_interval = int(getattr(settings, "FIELD_RECONCILER_INTERVAL_SECONDS", 900))
    _scheduler.add_job(
        reconcile_once,
        trigger=IntervalTrigger(seconds=reconcile_interval),
        id="field_intelligence_pending_reconcile",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Field Intelligence worker started (interval=%ss, reconcile=%ss)", interval, reconcile_interval
    )
    return _scheduler


def stop_field_intelligence_worker() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        finally:
            _scheduler = None

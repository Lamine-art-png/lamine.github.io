"""Background scheduler for periodic WiseConn data sync.

Uses APScheduler to run full_sync() on a configurable interval,
keeping AGRO-AI telemetry and irrigation data fresh.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.adapters.registry import AdapterRegistry
from app.core.config import settings
from app.core.metrics import sync_runs_total, sync_duration
from app.db.base import SessionLocal
from app.services.wiseconn_sync import WiseConnSyncService

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_last_sync_result: Optional[Dict[str, Any]] = None


async def run_wiseconn_sync() -> None:
    """Execute a full WiseConn sync cycle.

    Called periodically by the scheduler. Creates its own DB session
    and adapter per run to avoid stale connections.
    """
    global _last_sync_result
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    logger.info("Scheduled sync starting (run_id=%s)", run_id)

    if not settings.WISECONN_API_KEY:
        logger.warning("Skipping sync: WISECONN_API_KEY not set")
        return

    start_time = time.time()
    db = SessionLocal()
    try:
        registry = AdapterRegistry()
        adapter = registry.get_wiseconn()

        sync_service = WiseConnSyncService(adapter=adapter, db=db)
        result = await sync_service.full_sync(
            tenant_id="wiseconn-demo",
            days=settings.SYNC_LOOKBACK_DAYS,
        )

        sync_runs_total.labels(status="success").inc()
        sync_duration.observe(time.time() - start_time)

        _last_sync_result = {
            "run_id": run_id,
            "completed_at": datetime.utcnow().isoformat(),
            "status": "success" if not result.get("errors") else "partial",
            "summary": {
                "farms": len(result.get("discovery", {}).get("farms", [])),
                "blocks": len(result.get("blocks_created", [])),
                "telemetry_zones": len(result.get("telemetry", [])),
                "irrigation_zones": len(result.get("irrigations", [])),
                "errors": result.get("errors", []),
            },
        }
        logger.info(
            "Scheduled sync completed (run_id=%s): %s",
            run_id, _last_sync_result["status"],
        )

    except Exception as e:
        sync_runs_total.labels(status="error").inc()
        sync_duration.observe(time.time() - start_time)
        logger.error("Scheduled sync failed (run_id=%s): %s", run_id, e, exc_info=True)
        _last_sync_result = {
            "run_id": run_id,
            "completed_at": datetime.utcnow().isoformat(),
            "status": "error",
            "error": str(e),
        }
    finally:
        db.close()
        if hasattr(adapter, "close"):
            await adapter.close()


def get_last_sync_result() -> Optional[Dict[str, Any]]:
    """Get the result of the last sync run (for health checks)."""
    return _last_sync_result


def start_scheduler() -> AsyncIOScheduler:
    """Create and start the background scheduler."""
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()

    # WiseConn sync job — runs every SYNC_INTERVAL_MINUTES
    _scheduler.add_job(
        run_wiseconn_sync,
        trigger=IntervalTrigger(minutes=settings.SYNC_INTERVAL_MINUTES),
        id="wiseconn_sync",
        name="WiseConn Full Sync",
        replace_existing=True,
        max_instances=1,  # prevent overlapping runs
    )

    _scheduler.start()
    logger.info(
        "Background scheduler started: WiseConn sync every %d minutes",
        settings.SYNC_INTERVAL_MINUTES,
    )
    return _scheduler


def stop_scheduler() -> None:
    """Stop the background scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Background scheduler stopped")

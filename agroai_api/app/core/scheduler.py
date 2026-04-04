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
from app.models.block import Block
from app.models.water_state import WaterState
from app.services.wiseconn_sync import WiseConnSyncService
from app.services.feature_builder import FeatureBuilder
from app.services.water_state_engine import WaterStateEngine
from app.services.recommendation_outcome_tracker import RecommendationOutcomeTracker
from app.services.schedule_match_runner import ScheduleMatchRunner

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_last_sync_result: Optional[Dict[str, Any]] = None


def _run_water_state_estimation(db, tenant_id: str) -> int:
    """Estimate water state for all blocks belonging to a tenant.

    Runs after each sync cycle to keep water state fresh.
    Returns the number of blocks processed.
    """
    import uuid as _uuid

    blocks = db.query(Block).filter(Block.tenant_id == tenant_id).all()
    if not blocks:
        return 0

    builder = FeatureBuilder()
    engine = WaterStateEngine()
    count = 0

    for block in blocks:
        try:
            fs = builder.build(db, block.id)
            estimate = engine.estimate(fs)

            ws = WaterState(
                id=str(_uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block.id,
                estimated_at=estimate.estimated_at,
                root_zone_vwc=estimate.root_zone_vwc,
                depth_profile=estimate.depth_profile,
                stress_risk=estimate.stress_risk,
                refill_status=estimate.refill_status,
                depletion_rate=estimate.depletion_rate,
                hours_to_stress=estimate.hours_to_stress,
                et_demand_mm_day=estimate.et_demand_mm_day,
                last_irrigation_at=estimate.last_irrigation_at,
                last_irrigation_volume_m3=estimate.last_irrigation_volume_m3,
                confidence=estimate.confidence,
                anomaly_flags=estimate.anomaly_flags,
                feature_snapshot=estimate.feature_snapshot,
                engine_version=estimate.engine_version,
            )
            db.add(ws)
            count += 1
        except Exception as e:
            logger.warning(
                "Water state estimation failed for block %s: %s",
                block.id, e,
            )

    if count > 0:
        db.commit()
    logger.info("Water state estimated for %d/%d blocks", count, len(blocks))
    return count


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

        # Run water state estimation for all blocks after sync
        water_state_count = _run_water_state_estimation(db, "wiseconn-demo")

        # Run schedule matching (must happen before verification)
        match_summary = {"forward_matched": 0, "retroactive_created": 0}
        try:
            match_runner = ScheduleMatchRunner()
            match_summary = match_runner.run(db, "wiseconn-demo")
        except Exception as e:
            logger.warning("Schedule matching failed: %s", e)

        # Run outcome tracking for pending decision runs
        outcome_count = 0
        try:
            tracker = RecommendationOutcomeTracker()
            outcome_count = tracker.run(db, "wiseconn-demo")
        except Exception as e:
            logger.warning("Outcome tracking failed: %s", e)

        _last_sync_result = {
            "run_id": run_id,
            "completed_at": datetime.utcnow().isoformat(),
            "status": "success" if not result.get("errors") else "partial",
            "summary": {
                "farms": len(result.get("discovery", {}).get("farms", [])),
                "blocks": len(result.get("blocks_created", [])),
                "telemetry_zones": len(result.get("telemetry", [])),
                "irrigation_zones": len(result.get("irrigations", [])),
                "water_states_estimated": water_state_count,
                "schedules_matched": match_summary.get("forward_matched", 0),
                "retroactive_decisions": match_summary.get("retroactive_created", 0),
                "verifications_processed": outcome_count,
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

    # Run first sync 30 seconds after startup (non-blocking)
    from datetime import timedelta
    _scheduler.add_job(
        run_wiseconn_sync,
        trigger="date",
        run_date=datetime.utcnow() + timedelta(seconds=30),
        id="wiseconn_initial_sync",
        name="WiseConn Initial Sync",
        max_instances=1,
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

"""Always-on background worker for Field Intelligence.

Drains durable Field Intelligence processing, WhatsApp ingress/outbox, and
asset-deletion queues. Every queue uses independent idempotency and lease
semantics; one provider failure cannot crash the scheduler.
"""
from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.field_intelligence import FieldWorkerHeartbeat
from app.models.operational_records import IngestionJob
from app.models.whatsapp import WhatsAppInboundEvent, WhatsAppOutboundMessage
from app.services import field_intelligence as svc
from app.services import whatsapp_field_intelligence as whatsapp_svc
from app.services.field_intelligence_vision_extension import install_field_vision_extension
from app.services.release_contract import runtime_build_sha

install_field_vision_extension(svc)

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_WORKER_INSTANCE_ID = f"fi-worker-{socket.gethostname()[:40]}-{uuid.uuid4().hex[:8]}"

_FIELD_JOB_TYPES = (
    svc.PROCESS_JOB_TYPE,
    svc.ASSET_DELETE_JOB_TYPE,
    svc.ORPHAN_CLEANUP_JOB_TYPE,
)


def record_worker_heartbeat(db, worker_id: str, tick: dict | None = None) -> None:
    """Upsert this worker instance's liveness row (SHA-bearing)."""
    row = db.get(FieldWorkerHeartbeat, worker_id)
    now = datetime.utcnow()
    if row is None:
        row = FieldWorkerHeartbeat(
            worker_id=worker_id,
            hostname=socket.gethostname()[:120],
            git_sha=runtime_build_sha() or None,
            started_at=now,
            last_heartbeat_at=now,
            last_tick_json=tick or {},
        )
        db.add(row)
    else:
        row.last_heartbeat_at = now
        row.git_sha = runtime_build_sha() or row.git_sha
        row.last_tick_json = tick or {}
    db.commit()


def queue_health(db) -> dict:
    """Queue depth and stale-job detection for the Field Intelligence plane."""
    from app.services.field_intelligence_metrics import queue_depth, stale_jobs

    stale_after = timedelta(seconds=int(getattr(settings, "FIELD_STALE_JOB_ALERT_SECONDS", 900)))
    cutoff = datetime.utcnow() - stale_after
    report: dict = {"depth": {}, "stale": {}, "whatsapp": {}}
    for job_type in _FIELD_JOB_TYPES:
        depths: dict[str, int] = {}
        for job_status in ("queued", "running", "failed"):
            count = (
                db.query(IngestionJob)
                .filter(IngestionJob.job_type == job_type)
                .filter(IngestionJob.status == job_status)
                .count()
            )
            depths[job_status] = count
            queue_depth.labels(job_type=job_type, status=job_status).set(count)
        stale = (
            db.query(IngestionJob)
            .filter(IngestionJob.job_type == job_type)
            .filter(IngestionJob.status.in_(["queued", "running"]))
            .filter(IngestionJob.created_at <= cutoff)
            .count()
        )
        stale_jobs.labels(job_type=job_type).set(stale)
        report["depth"][job_type] = depths
        report["stale"][job_type] = stale

    report["whatsapp"] = {
        "inbound_queued": db.query(WhatsAppInboundEvent).filter(
            WhatsAppInboundEvent.status.in_(["queued", "processing"])
        ).count(),
        "inbound_failed": db.query(WhatsAppInboundEvent).filter(
            WhatsAppInboundEvent.status == "failed"
        ).count(),
        "outbound_queued": db.query(WhatsAppOutboundMessage).filter(
            WhatsAppOutboundMessage.status.in_(["queued", "sending"])
        ).count(),
        "outbound_failed": db.query(WhatsAppOutboundMessage).filter(
            WhatsAppOutboundMessage.status == "failed"
        ).count(),
    }
    return report


def worker_status(db) -> dict:
    """Operational status: live instances, SHAs, queue health (admin surface)."""
    ttl = int(getattr(settings, "FIELD_WORKER_HEARTBEAT_TTL_SECONDS", 120))
    cutoff = datetime.utcnow() - timedelta(seconds=ttl)
    instances = [
        {
            "worker_id": row.worker_id,
            "hostname": row.hostname,
            "git_sha": row.git_sha,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
            "live": bool(row.last_heartbeat_at and row.last_heartbeat_at >= cutoff),
        }
        for row in db.query(FieldWorkerHeartbeat).order_by(FieldWorkerHeartbeat.last_heartbeat_at.desc()).limit(50)
    ]
    return {"instances": instances, "queue": queue_health(db)}


def drain_once(*, worker_id: str | None = None) -> dict:
    """Process a bounded slice of every durable Field Intelligence queue."""
    from app.services.field_intelligence_rollout import kill_switch_active

    worker_id = worker_id or _WORKER_INSTANCE_ID
    db = SessionLocal()
    try:
        batch = int(getattr(settings, "FIELD_WORKER_BATCH", 25))
        paused = kill_switch_active(db)
        if paused:
            processed = {"skipped": "kill_switch"}
            whatsapp_ingress = {"skipped": "kill_switch"}
        else:
            processed = svc.run_field_intelligence_jobs(db, limit=batch, worker_id=worker_id)
            whatsapp_ingress = whatsapp_svc.run_whatsapp_ingress_jobs(
                db, limit=batch, worker_id=worker_id
            )
        whatsapp_outbound = whatsapp_svc.run_whatsapp_outbox(
            db, limit=batch, worker_id=worker_id
        )
        deletions = svc.run_field_intelligence_deletions(db, limit=batch, worker_id=worker_id)
        orphans = svc.run_field_intelligence_orphan_cleanup(db, limit=batch, worker_id=worker_id)
        tick = {
            "processing": processed,
            "whatsapp_ingress": whatsapp_ingress,
            "whatsapp_outbound": whatsapp_outbound,
            "deletions": deletions,
            "orphan_cleanup": orphans,
            "paused": paused,
        }
        record_worker_heartbeat(db, worker_id, tick)
        queue_health(db)
        return tick
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
    total_whatsapp_ingress = 0
    total_whatsapp_outbound = 0
    for _ in range(max_rounds):
        wa_in = whatsapp_svc.run_whatsapp_ingress_jobs(db, limit=50)
        proc = svc.run_field_intelligence_jobs(db, limit=50)
        wa_out = whatsapp_svc.run_whatsapp_outbox(db, limit=50)
        dele = svc.run_field_intelligence_deletions(db, limit=50)
        orph = svc.run_field_intelligence_orphan_cleanup(db, limit=50)
        total_whatsapp_ingress += wa_in.get("processed", 0)
        total_processed += proc.get("processed", 0)
        total_whatsapp_outbound += wa_out.get("sent", 0)
        total_deleted += dele.get("deleted", 0)
        total_cleaned += orph.get("cleaned", 0)
        if (
            wa_in.get("processed", 0) == 0
            and wa_in.get("failed", 0) == 0
            and proc.get("processed", 0) == 0
            and proc.get("failed", 0) == 0
            and wa_out.get("sent", 0) == 0
            and wa_out.get("failed", 0) == 0
            and dele.get("deleted", 0) == 0
            and orph.get("cleaned", 0) == 0
        ):
            break
    return {
        "processed": total_processed,
        "whatsapp_ingress": total_whatsapp_ingress,
        "whatsapp_outbound": total_whatsapp_outbound,
        "deleted": total_deleted,
        "cleaned": total_cleaned,
    }


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

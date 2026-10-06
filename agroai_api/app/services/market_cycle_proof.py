"""Operator proof of the live Commercial Intelligence cycle (read-only).

Answers one question from persisted rows only: did a real cycle schedule
durable jobs, publish them, complete shared ingestion and evaluate at least one
organization without ever evaluating on evidence older than its slot's
refresh?

Everything returned is an aggregate count, a timestamp, a status word or the
deployed build SHA. No organization, user, position, commodity, price,
contract or observation value is ever returned: the response is printed in
public workflow logs.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.market_intelligence import MarketCycleOrganizationState, MarketPosition, MarketProviderRun
from app.models.operational_records import IngestionJob
from app.models.saas import Organization
from app.models.task_outbox import TaskOutbox
from app.services.market_intelligence_cycle import (
    OPEN_JOB_STATUSES,
    SHARED_INGESTION_INCOMPLETE,
    SLOT_MARKER_PROVIDER,
    TASK_TYPE,
    cycle_enabled,
)
from app.services.redis_task_queue import queue_configured
from app.services.release_contract import runtime_build_sha

PROOF_CONTRACT = "market-cycle-proof-v1"
DEFAULT_WINDOW = timedelta(hours=2)
MAX_WINDOW = timedelta(hours=48)
MAX_JOBS = 5000

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"
NO_ELIGIBLE_POSITION = "NO_ELIGIBLE_POSITION"
CYCLE_DISABLED = "CYCLE_DISABLED"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def window_start(since: datetime | None, now: datetime) -> datetime:
    if since is None:
        return now - DEFAULT_WINDOW
    if since.tzinfo is not None:
        since = since.replace(tzinfo=None) - (since.utcoffset() or timedelta())
    return max(since, now - MAX_WINDOW)


def _eligibility(db: Session) -> dict[str, int]:
    # Same population the scheduler admits: active positions of existing organizations.
    row = (
        db.query(func.count(func.distinct(MarketPosition.organization_id)), func.count(MarketPosition.id))
        .join(Organization, Organization.id == MarketPosition.organization_id)
        .filter(MarketPosition.status == "active")
        .one()
    )
    return {"eligible_organizations": int(row[0] or 0), "eligible_positions": int(row[1] or 0)}


def _slot_summary(run: MarketProviderRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    providers = (run.trace_json or {}).get("providers") or {}
    return {
        "slot": str(run.demand_key).removeprefix("slot:"),
        "trigger": run.trigger,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        # A marker row is only written once every provider of the slot finished.
        "shared_ingestion_complete": run.status == "ok" and run.finished_at is not None,
        "provider_status_counts": dict(Counter(str(value) for value in providers.values())),
    }


def cycle_proof(db: Session, *, since: datetime | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.utcnow()
    start = window_start(since, now)
    enabled = cycle_enabled()
    eligibility = _eligibility(db)

    jobs = (
        db.query(IngestionJob.id, IngestionJob.tenant_id, IngestionJob.status, IngestionJob.input_json, IngestionJob.output_json)
        .filter(IngestionJob.job_type == TASK_TYPE, IngestionJob.created_at >= start)
        .order_by(IngestionJob.created_at.desc())
        .limit(MAX_JOBS)
        .all()
    )
    job_ids = [job.id for job in jobs]
    outbox_status: Counter[str] = Counter()
    published = 0
    if job_ids:
        for status, published_at in db.query(TaskOutbox.status, TaskOutbox.published_at).filter(TaskOutbox.job_id.in_(job_ids)).all():
            outbox_status[str(status)] += 1
            published += 1 if published_at is not None or status == "published" else 0

    slots = {str((job.input_json or {}).get("slot") or "") for job in jobs} - {""}
    marked = {
        str(key).removeprefix("slot:")
        for (key,) in db.query(MarketProviderRun.demand_key).filter(
            MarketProviderRun.provider == SLOT_MARKER_PROVIDER,
            MarketProviderRun.status == "ok",
            MarketProviderRun.demand_key.in_([f"slot:{slot}" for slot in slots]),
        ).all()
    } if slots else set()

    by_status: Counter[str] = Counter()
    evaluated_orgs: set[str] = set()
    fully_evaluated_orgs: set[str] = set()
    positions_evaluated = failed_positions = 0
    shared_incomplete = without_shared_ingestion = without_slot_marker = 0
    successful_slots: set[str] = set()
    for job in jobs:
        by_status[str(job.status)] += 1
        output = job.output_json or {}
        slot = str((job.input_json or {}).get("slot") or "")
        evaluated = int(output.get("evaluated") or 0)
        if output.get("status") == SHARED_INGESTION_INCOMPLETE:
            shared_incomplete += 1
        if evaluated > 0:
            # The stale-evidence guarantee: evaluation only after the slot's
            # shared ingestion completed, and the slot marker proves it did.
            if output.get("shared_ingestion_complete") is not True:
                without_shared_ingestion += 1
            if slot not in marked:
                without_slot_marker += 1
        if job.status == "succeeded" and evaluated > 0 and output.get("shared_ingestion_complete") is True:
            evaluated_orgs.add(job.tenant_id)
            successful_slots.add(slot)
            positions_evaluated += evaluated
            failed_positions += int(output.get("failed_positions") or 0)
            if output.get("complete") is True:
                fully_evaluated_orgs.add(job.tenant_id)

    latest_marker = (
        db.query(MarketProviderRun)
        .filter(MarketProviderRun.provider == SLOT_MARKER_PROVIDER)
        .order_by(MarketProviderRun.started_at.desc())
        .first()
    )
    stale_leases = int(
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.job_type == TASK_TYPE, IngestionJob.status == "running",
                IngestionJob.lease_expires_at.is_not(None), IngestionJob.lease_expires_at <= now)
        .scalar() or 0
    )
    open_jobs = int(
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.job_type == TASK_TYPE, IngestionJob.status.in_(OPEN_JOB_STATUSES))
        .scalar() or 0
    )
    state_status = Counter(
        str(status) for (status,) in db.query(MarketCycleOrganizationState.last_status).all()
    )
    organizations_with_failures = int(
        db.query(func.count(MarketCycleOrganizationState.organization_id))
        .filter(MarketCycleOrganizationState.consecutive_failures > 0)
        .scalar() or 0
    )

    failed_jobs = by_status.get("failed", 0)
    reasons: list[str] = []
    if not enabled:
        verdict = CYCLE_DISABLED
    elif eligibility["eligible_positions"] == 0:
        verdict = NO_ELIGIBLE_POSITION
    else:
        if without_shared_ingestion:
            reasons.append("evaluation_without_completed_shared_ingestion")
        if without_slot_marker:
            reasons.append("evaluation_without_slot_ingestion_marker")
        if failed_jobs:
            reasons.append("cycle_jobs_failed")
        if reasons:
            verdict = FAIL
        elif evaluated_orgs and successful_slots <= marked:
            verdict = PASS
        else:
            verdict = PENDING
            reasons.append("no_successful_organization_cycle_yet" if jobs else "no_cycle_job_in_window")

    return {
        "status": "ok",
        "contract": PROOF_CONTRACT,
        "verdict": verdict,
        "reasons": reasons,
        "build_sha": runtime_build_sha() or None,
        "checked_at": _iso(now),
        "window_start": _iso(start),
        "cycle_enabled": enabled,
        "queue_configured": queue_configured(),
        "eligibility": eligibility,
        "latest_slot": _slot_summary(latest_marker),
        "jobs": {
            "scheduled": len(jobs),
            "published": published,
            "by_status": dict(by_status),
            "outbox_by_status": dict(outbox_status),
            "succeeded": by_status.get("succeeded", 0),
            "failed": failed_jobs,
            "shared_ingestion_incomplete": shared_incomplete,
        },
        "evaluation": {
            "organizations_evaluated": len(evaluated_orgs),
            "organizations_fully_evaluated": len(fully_evaluated_orgs),
            "positions_evaluated": positions_evaluated,
            "positions_failed": failed_positions,
            "slots_with_completed_shared_ingestion": len(successful_slots & marked),
            "evaluations_without_completed_shared_ingestion": without_shared_ingestion,
            "evaluations_without_slot_marker": without_slot_marker,
        },
        "health": {
            "open_jobs": open_jobs,
            "stale_running_leases": stale_leases,
            "organizations_with_consecutive_failures": organizations_with_failures,
            "organization_state_counts": dict(state_status),
        },
    }

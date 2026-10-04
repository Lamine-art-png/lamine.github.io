"""Asynchronous intelligence jobs.

A job is a ``CommercialIntelligenceRun`` with ``execution='async'``: one
idempotency namespace, one money path, one result store. No new queue
infrastructure: dispatch uses the existing durable task transport (Cloudflare
Queue via the edge gateway in production, Redis Streams where configured),
and the hourly maintenance drain re-dispatches anything a publish missed.

Lifecycle::

    queued -> running(processing) -> completed | degraded | failed
       |            |                     (no charge unless completed)
       +-> canceled +-> canceled (cancel requested; closed without charge)
                    +-> timeout  (lease expired; closed without charge)
    transient failure -> queued again with backoff, at most 3 attempts.

Claiming is a compare-and-set under ``FOR UPDATE SKIP LOCKED`` so a job is
executed by exactly one worker at a time; a duplicate queue delivery observes
a non-queued row and acknowledges without work. Billing happens only inside
the shared completion transaction, so a job is charged at most once.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.intelligence_commerce import CommercialIntelligenceRun
from app.platform_api.principal import PlatformPrincipal


logger = logging.getLogger("agroai.intelligence.jobs")

INTELLIGENCE_JOB_TASK_TYPE = "platform_intelligence_job"
JOB_LEASE = timedelta(minutes=8)
RESULT_RETENTION_DAYS = 30
_TERMINAL = {"completed", "degraded", "failed", "canceled", "timeout"}


def public_status(run: CommercialIntelligenceRun) -> str:
    return "running" if run.status == "processing" else run.status


def job_public(run: CommercialIntelligenceRun) -> dict[str, Any]:
    status = public_status(run)
    result = dict(run.response_json) if run.response_json is not None and status in {"completed", "degraded"} else None
    error = None
    if status in {"failed", "timeout", "canceled"} or (status == "queued" and run.error_code):
        error = {"code": run.error_code or status}
    return {
        "id": run.id,
        "object": "agroai.intelligence.job",
        "status": status,
        "task": run.task,
        "model": run.public_model,
        "attempts": int(run.attempt_count or 0),
        "price_cents": int(run.charge_cents or 0),
        "charged": status == "completed",
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "next_attempt_at": run.next_attempt_at.isoformat() if run.next_attempt_at and status == "queued" else None,
        "cancel_requested": run.cancel_requested_at is not None,
        "metadata": dict(run.metadata_json or {}),
        "result": result,
        "error": error,
    }


def owned_run(db: Session, principal: PlatformPrincipal, run_id: str, *, execution: str | None = None) -> CommercialIntelligenceRun:
    query = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.id == run_id,
        CommercialIntelligenceRun.organization_id == principal.organization_id,
        CommercialIntelligenceRun.api_project_id == principal.api_project_id,
    )
    if execution is not None:
        query = query.filter(CommercialIntelligenceRun.execution == execution)
    if principal.workspace_id:
        # Exact match: a workspace-restricted key never sees project-wide runs.
        query = query.filter(CommercialIntelligenceRun.workspace_id == principal.workspace_id)
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "intelligence_job_not_found" if execution == "async" else "intelligence_run_not_found"})
    return row


def dispatch(run_id: str, organization_id: str) -> bool:
    """Best-effort immediate publish; the maintenance drain is the durable path."""
    try:
        from app.services.redis_task_queue import get_task_publisher, queue_configured

        if not queue_configured():
            return False
        get_task_publisher().enqueue(run_id, organization_id, INTELLIGENCE_JOB_TASK_TYPE)
        return True
    except Exception:  # noqa: BLE001 - row stays queued; the drain re-dispatches
        logger.warning("intelligence_job_dispatch_deferred run_id=%s", run_id)
        return False


def cancel(db: Session, principal: PlatformPrincipal, run_id: str) -> CommercialIntelligenceRun:
    owned_run(db, principal, run_id, execution="async")
    run = (
        db.query(CommercialIntelligenceRun)
        .filter(CommercialIntelligenceRun.id == run_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if run.status in _TERMINAL:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "intelligence_job_already_finished", "status": public_status(run)})
    now = datetime.utcnow()
    run.cancel_requested_at = now
    if run.status == "queued":
        run.status = "canceled"
        run.error_code = "intelligence_job_canceled"
        run.completed_at = now
        run.request_payload_json = None
    db.commit()
    return run


def _principal_for(db: Session, run: CommercialIntelligenceRun) -> PlatformPrincipal | None:
    """Rebuild the caller's authority at execution time, not enqueue time.

    A key revoked, a project suspended, or a workspace restriction changed
    after enqueue must stop the job before it reaches inference.
    """
    from app.core.organization_access import organization_access_allowed
    from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
    from app.models.saas import Organization

    now = datetime.utcnow()
    project = db.get(ApiProject, run.api_project_id)
    if project is None or project.organization_id != run.organization_id or project.status != "active":
        return None
    if not organization_access_allowed(db.get(Organization, run.organization_id)):
        return None
    workspace_id = None
    if run.api_key_id:
        key = db.get(PlatformApiKey, run.api_key_id)
        if (
            key is None
            or key.status != "active"
            or key.revoked_at is not None
            or key.organization_id != run.organization_id
            or key.api_project_id != run.api_project_id
            or "intelligence:run" not in set(key.scopes or [])
            or (key.expires_at is not None and key.expires_at <= now)
            or (key.overlap_expires_at is not None and key.overlap_expires_at <= now)
        ):
            return None
        service_account = db.get(ApiServiceAccount, key.service_account_id)
        if service_account is None or service_account.status != "active":
            return None
        workspace_id = key.workspace_id
        resource_restrictions = dict(key.resource_restrictions_json or {})
        provider_restrictions = dict(key.provider_restrictions_json or {})
    else:
        resource_restrictions, provider_restrictions = {}, {}
    return PlatformPrincipal(
        authentication_type="platform_api_key" if run.api_key_id else "portal_user",
        organization_id=run.organization_id,
        workspace_id=workspace_id or (run.workspace_id if not run.api_key_id else None),
        api_project_id=run.api_project_id,
        api_key_id=run.api_key_id,
        scopes=frozenset({"intelligence:run"}),
        environment="live",
        request_id=run.request_id or run.id,
        resource_restrictions=resource_restrictions,
        provider_restrictions=provider_restrictions,
        actor_metadata={"commercial_intelligence": True, "async_job": True},
    )


def _close(db: Session, run: CommercialIntelligenceRun, status: str, code: str) -> str:
    run.status = status
    run.error_code = code
    run.completed_at = datetime.utcnow()
    run.request_payload_json = None
    run.lease_expires_at = None
    db.commit()
    return status


async def execute_job(db: Session, *, run_id: str, organization_id: str, worker_id: str) -> str:
    """Claim and execute one job. Returns the resulting public status."""
    from app.api.v1 import commercial_intelligence as legacy
    from app.api.v1 import commercial_intelligence_hardened as hardened
    now = datetime.utcnow()
    run = (
        db.query(CommercialIntelligenceRun)
        .filter(
            CommercialIntelligenceRun.id == run_id,
            CommercialIntelligenceRun.organization_id == organization_id,
            CommercialIntelligenceRun.execution == "async",
        )
        .with_for_update(skip_locked=True)
        .populate_existing()
        .first()
    )
    if run is None:
        db.rollback()
        return "succeeded"  # unknown, foreign, or being claimed elsewhere: acknowledge
    if run.status != "queued":
        status = public_status(run)
        db.rollback()
        return status
    if run.next_attempt_at and run.next_attempt_at > now + timedelta(seconds=5):
        db.rollback()
        return "queued"
    principal = _principal_for(db, run)
    if principal is None:
        return _close(db, run, "failed", "intelligence_job_authority_revoked")
    if not run.request_payload_json:
        return _close(db, run, "failed", "intelligence_job_payload_missing")
    try:
        payload = legacy.IntelligenceRequest.model_validate(run.request_payload_json)
    except Exception:  # noqa: BLE001
        return _close(db, run, "failed", "intelligence_job_payload_invalid")

    run.status = "processing"
    run.started_at = now
    run.attempt_count = int(run.attempt_count or 0) + 1
    run.lease_expires_at = now + JOB_LEASE
    run.error_code = None
    db.commit()

    try:
        admitted = hardened._readmit_paid_run(payload=payload, principal=principal, db=db, run=run)
    except HTTPException as exc:
        # A referenced session/file was deleted, or a boundary changed, after enqueue.
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else "intelligence_job_reference_invalid"
        hardened._fail_unstarted_run(db, run_id=run_id, code=str(code))
        return "failed"
    try:
        await hardened._complete_paid_run(payload=payload, principal=principal, db=db, admitted=admitted)
    except HTTPException:
        pass  # terminal or retry state already recorded on the row
    final = db.query(CommercialIntelligenceRun).filter(CommercialIntelligenceRun.id == run_id).populate_existing().one()
    db.commit()
    logger.info(
        "intelligence_job_executed run_id=%s status=%s attempts=%s worker=%s latency_ms=%s",
        run_id, final.status, final.attempt_count, worker_id, final.latency_ms,
    )
    return public_status(final)


def process_intelligence_job(*, job_id: str, organization_id: str, worker_id: str) -> str:
    """Queue-consumer entry point (sync; runs the async executor to completion)."""
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        status = asyncio.run(execute_job(db, run_id=job_id, organization_id=organization_id, worker_id=worker_id))
    finally:
        db.close()
    if status in _TERMINAL or status == "succeeded":
        return "succeeded"
    if status == "queued":
        # Retry scheduled with backoff; the drain re-dispatches when due. Ack
        # this delivery so the queue does not hot-loop.
        return "succeeded"
    if status == "running":
        return "succeeded"  # another worker holds the lease
    return "failed"


def sweep(db: Session, *, limit: int = 25) -> dict[str, int]:
    """Maintenance: time out expired leases (no charge) and re-dispatch due jobs."""
    now = datetime.utcnow()
    timed_out = 0
    expired = (
        db.query(CommercialIntelligenceRun)
        .filter(
            CommercialIntelligenceRun.execution == "async",
            CommercialIntelligenceRun.status == "processing",
            CommercialIntelligenceRun.lease_expires_at.isnot(None),
            CommercialIntelligenceRun.lease_expires_at <= now,
        )
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for run in expired:
        # Nothing was charged: the debit only exists inside the completion
        # transaction, which never committed for an expired lease.
        run.status = "timeout"
        run.error_code = "intelligence_job_timeout"
        run.completed_at = now
        run.request_payload_json = None
        timed_out += 1
    db.commit()

    due = (
        db.query(CommercialIntelligenceRun.id, CommercialIntelligenceRun.organization_id)
        .filter(
            CommercialIntelligenceRun.execution == "async",
            CommercialIntelligenceRun.status == "queued",
            CommercialIntelligenceRun.next_attempt_at <= now - timedelta(seconds=30),
        )
        .order_by(CommercialIntelligenceRun.next_attempt_at.asc())
        .limit(limit)
        .all()
    )
    dispatched = sum(1 for run_id, organization_id in due if dispatch(run_id, organization_id))
    return {"timed_out": timed_out, "redispatched": dispatched, "due": len(due)}


def purge_expired_payloads_and_results(db: Session, *, limit: int = 500) -> int:
    """Result retention: drop stored responses of async jobs older than the retention window."""
    cutoff = datetime.utcnow() - timedelta(days=RESULT_RETENTION_DAYS)
    rows = (
        db.query(CommercialIntelligenceRun)
        .filter(
            CommercialIntelligenceRun.execution == "async",
            CommercialIntelligenceRun.completed_at.isnot(None),
            CommercialIntelligenceRun.completed_at < cutoff,
            CommercialIntelligenceRun.response_json.isnot(None),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    for run in rows:
        run.response_json = {"id": run.id, "object": "agroai.intelligence", "status": run.status, "result_expired": True}
    db.commit()
    return len(rows)

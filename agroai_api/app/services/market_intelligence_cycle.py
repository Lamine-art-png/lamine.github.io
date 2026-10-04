"""Scheduled Commercial Intelligence cycle on AGRO-AI's durable job queue.

The hourly maintenance hook (Cloudflare cron -> drain-outbox) only *schedules*:
it writes one durable job per due organization (``ingestion_jobs`` +
``task_outbox``, the same infrastructure as connector and Platform API jobs),
and the outbox publishes them to the Cloudflare Queue, which delivers each to
``/v1/internal/queue/connector-task``. Nothing runs after the HTTP response,
so a deploy or process restart cannot silently lose a cycle:

- a job that crashes mid-run keeps its row; its lease expires and the next
  scheduling tick re-arms its outbox row for redelivery;
- failures retry with backoff up to ``max_attempts`` (``_fail_or_retry``), then
  stay visibly ``failed`` in the job row and the organization state;
- single-flight: at most one open job per organization (open-job check plus a
  per-hour idempotency key backed by a unique index), job claims are
  lease-fenced, and shared provider ingestion holds a per-provider lock.

Fair, bounded scheduling: each tick enqueues at most ``batch`` organizations,
oldest-due first (never run first, then the oldest completion), so a large
tenant population cannot starve later organizations. Inside a job, positions
are refreshed oldest-first under a time budget, so partial progress rotates.

Each organization job:
1. ingests due shared provider demands once for all tenants (dedupe by demand
   hash + freshness; the first job of a tick does the work, others find the
   evidence fresh);
2. re-resolves the organization's active positions from the shared plane;
3. snapshots economics and evaluates materiality;
4. delivers alerts (in-app always; email only when explicitly enabled), with
   per-recipient attempts recorded separately from successful delivery.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator

from sqlalchemy import and_, func, literal, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market_intelligence import (
    MarketAlertDelivery,
    MarketCycleOrganizationState,
    MarketMaterialityEvent,
    MarketPosition,
    MarketProviderRun,
)
from app.models.operational_records import IngestionJob
from app.models.saas import Organization, OrganizationMembership, User, UserPreference
from app.models.task_outbox import TaskOutbox
from app.services import market_data_plane as plane
from app.services.ingestion_job_runner import _claim, _complete, _fail_or_retry, job_lease_heartbeat
from app.services.market_data_adapters import ADAPTERS
from app.services.market_intelligence_refresh import refresh_position_market_data
from app.services.market_materiality import evaluate_position

logger = logging.getLogger("agroai.market_cycle")

TASK_TYPE = "market_intelligence_cycle"
OPEN_JOB_STATUSES = ("queued", "running", "retrying")
CYCLE_INTERVAL = timedelta(minutes=55)  # an organization is due about hourly
DEFAULT_BATCH = 200
# The queue consumer waits 120 s for a delivery; finish well inside it.
DEFAULT_JOB_TIME_BUDGET_SECONDS = 90.0
STALE_DELIVERY_AFTER = timedelta(minutes=10)
_EPOCH = datetime(1970, 1, 1)
_provider_locks: dict[str, threading.Lock] = {}
_provider_locks_guard = threading.Lock()


def _flag(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def cycle_enabled() -> bool:
    raw = str(os.getenv("MARKET_INTELLIGENCE_CYCLE_ENABLED", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


def _state(db: Session, organization_id: str) -> MarketCycleOrganizationState:
    row = db.get(MarketCycleOrganizationState, organization_id)
    if row is None:
        row = MarketCycleOrganizationState(organization_id=organization_id, consecutive_failures=0)
        db.add(row)
        db.flush()
    return row


# ---------------------------------------------------------------------------
# Scheduling (runs inside the hourly drain request; enqueue only)
# ---------------------------------------------------------------------------


def _slot(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H")


def recover_stale_jobs(db: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Re-arm delivery for cycle jobs whose delivery was lost.

    Covers a worker killed mid-run (running, lease expired), a retry whose
    queue redelivery was exhausted (retrying, due) and a queued job whose
    published message never arrived. The job row is the source of truth; the
    lease prevents concurrent execution of a re-delivered job.
    """
    now = now or datetime.utcnow()
    stale_before = now - STALE_DELIVERY_AFTER
    rows = (
        db.query(TaskOutbox)
        .join(IngestionJob, IngestionJob.id == TaskOutbox.job_id)
        .filter(
            TaskOutbox.task_type == TASK_TYPE,
            TaskOutbox.status.in_(["published", "publishing"]),
            TaskOutbox.updated_at <= stale_before,
            or_(
                and_(IngestionJob.status == "running", IngestionJob.lease_expires_at.isnot(None), IngestionJob.lease_expires_at <= now),
                and_(IngestionJob.status == "retrying", or_(IngestionJob.next_attempt_at.is_(None), IngestionJob.next_attempt_at <= now)),
                and_(IngestionJob.status == "queued", IngestionJob.updated_at <= stale_before),
            ),
        )
        .order_by(TaskOutbox.updated_at.asc())
        .limit(limit)
        .all()
    )
    for row in rows:
        row.status = "pending"
        row.next_attempt_at = now
        row.published_at = None
        row.last_error = "Stale market intelligence cycle job re-armed for delivery."
        row.updated_at = now
    if rows:
        db.commit()
    return len(rows)


def due_organizations(db: Session, *, now: datetime, limit: int) -> list[str]:
    """Organizations with active positions, oldest-due first, without an open job."""
    open_jobs = (
        db.query(IngestionJob.tenant_id)
        .filter(IngestionJob.job_type == TASK_TYPE, IngestionJob.status.in_(OPEN_JOB_STATUSES))
        .subquery()
    )
    with_positions = (
        db.query(MarketPosition.organization_id.label("organization_id"))
        .filter(MarketPosition.status == "active")
        .distinct()
        .subquery()
    )
    last_completed = func.coalesce(MarketCycleOrganizationState.last_completed_at, literal(_EPOCH))
    rows = (
        db.query(with_positions.c.organization_id)
        .join(Organization, Organization.id == with_positions.c.organization_id)
        .outerjoin(MarketCycleOrganizationState, MarketCycleOrganizationState.organization_id == with_positions.c.organization_id)
        .filter(~with_positions.c.organization_id.in_(db.query(open_jobs.c.tenant_id)))
        .filter(last_completed <= now - CYCLE_INTERVAL)
        .order_by(last_completed.asc(), func.coalesce(MarketCycleOrganizationState.last_enqueued_at, literal(_EPOCH)).asc(), with_positions.c.organization_id.asc())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def enqueue_organization(db: Session, organization_id: str, *, now: datetime, trigger: str = "scheduled") -> IngestionJob | None:
    """One durable job per organization per hour slot (idempotent)."""
    identity = hashlib.sha256(f"{organization_id}|{TASK_TYPE}|{_slot(now)}".encode()).hexdigest()
    try:
        with db.begin_nested():
            job = IngestionJob(
                tenant_id=organization_id,
                job_type=TASK_TYPE,
                status="queued",
                input_json={"trigger": trigger, "slot": _slot(now)},
                output_json={},
                idempotency_key=identity,
                attempt_count=0,
                max_attempts=int(getattr(settings, "TASK_QUEUE_MAX_ATTEMPTS", 5) or 5),
                created_at=now,
                updated_at=now,
            )
            db.add(job)
            db.flush()
            db.add(TaskOutbox(
                job_id=job.id,
                tenant_id=organization_id,
                task_type=TASK_TYPE,
                payload_json={"job_id": job.id, "slot": _slot(now)},
                status="pending",
                publish_attempts=0,
                created_at=now,
                updated_at=now,
            ))
            db.flush()
    except IntegrityError:
        return None  # another scheduler already enqueued this organization for this slot
    state = _state(db, organization_id)
    state.last_enqueued_at = now
    state.last_job_id = job.id
    state.last_status = "queued"
    return job


def schedule_cycle(db: Session, *, now: datetime | None = None, batch: int | None = None, trigger: str = "scheduled") -> dict[str, Any]:
    """Enqueue due organizations. Cheap and bounded; safe to call concurrently."""
    if not cycle_enabled():
        return {"status": "disabled"}
    now = now or datetime.utcnow()
    batch = batch or _int_env("MARKET_INTELLIGENCE_CYCLE_BATCH", DEFAULT_BATCH)
    # One total budget per tick: cycle rows already waiting to publish,
    # re-armed stale jobs and newly due organizations together never exceed
    # ``batch``, which is exactly what the same drain pass then publishes.
    pending = _publishable_cycle_rows(db, now)
    budget = max(0, batch - pending)
    recovered = recover_stale_jobs(db, now=now, limit=budget) if budget else 0
    budget -= recovered
    organizations = due_organizations(db, now=now, limit=budget) if budget > 0 else []
    enqueued = [job.id for organization_id in organizations if (job := enqueue_organization(db, organization_id, now=now, trigger=trigger)) is not None]
    db.commit()
    return {"status": "ok", "enqueued": len(enqueued), "recovered": recovered, "already_pending": pending, "batch": batch}


def _publishable_cycle_rows(db: Session, now: datetime) -> int:
    from app.services.task_outbox_service import _claimable_outbox

    return int(
        db.query(func.count(TaskOutbox.id))
        .filter(TaskOutbox.task_type == TASK_TYPE, _claimable_outbox(now))
        .scalar() or 0
    )


def schedule_cycle_once(**kwargs: Any) -> dict[str, Any]:
    """Thread-owned session entry point for the drain endpoint."""
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        return schedule_cycle(db, **kwargs)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Shared ingestion (single-flight per provider across workers)
# ---------------------------------------------------------------------------


@contextmanager
def _provider_lock(db: Session, provider_id: str) -> Iterator[bool]:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        key = zlib.crc32(f"market-provider:{provider_id}".encode()) & 0x7FFFFFFF
        acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                db.commit()
        return
    with _provider_locks_guard:
        lock = _provider_locks.setdefault(provider_id, threading.Lock())
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


async def ingest_due_demands(db: Session, *, deadline: float, trigger: str = "scheduled") -> dict[str, Any]:
    results: dict[str, Any] = {}
    for provider_id, selectors in plane.demand_set(db).items():
        adapter = ADAPTERS.get(provider_id)
        if adapter is None:
            continue
        if time.monotonic() > deadline:
            results[provider_id] = {"status": "deferred_time_budget"}
            continue
        if not adapter.configured():
            results[provider_id] = {"status": adapter.status().lower()}
            continue
        demand_key, _ = plane.demand_identity(adapter, selectors)
        if not plane.provider_due(db, adapter, demand_key):
            results[provider_id] = {"status": "fresh_enough"}
            continue
        with _provider_lock(db, provider_id) as acquired:
            if not acquired:
                results[provider_id] = {"status": "in_progress_elsewhere"}
                continue
            if not plane.provider_due(db, adapter, demand_key):  # another worker just finished it
                results[provider_id] = {"status": "fresh_enough"}
                continue
            try:
                results[provider_id] = await asyncio.wait_for(
                    plane.ingest(db, provider_id, selectors, trigger=trigger, adapter=adapter),
                    timeout=max(5.0, min(adapter.request_timeout_seconds + 30.0, deadline - time.monotonic())),
                )
            except asyncio.TimeoutError:
                db.rollback()
                results[provider_id] = {"status": "timeout"}
    return results


SLOT_MARKER_PROVIDER = "__cycle_slot__"
# Barrier: an organization job never evaluates before the slot's shared
# ingestion has completed. It is re-queued (not failed) a bounded number of
# times; after that it evaluates and reports the incomplete ingestion.
SLOT_DEFER_SECONDS = 30
MAX_SLOT_DEFERRALS = 20


class SlotIngestionPending(Exception):
    """Shared ingestion for this slot is still running (or unfinished)."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


async def ingest_once_per_slot(db: Session, slot: str, *, deadline: float, trigger: str = "scheduled") -> dict[str, Any]:
    """Shared ingestion runs once per scheduling slot, not once per organization.

    Building the global demand set reads every tenant's active positions, so
    only the first job of a slot does it (under a lock) and records a marker
    run; every other organization job of that slot skips straight to
    evaluation against the freshly persisted evidence.
    """
    marker_key = f"slot:{slot}"

    def marked() -> bool:
        return db.query(MarketProviderRun.id).filter(
            MarketProviderRun.provider == SLOT_MARKER_PROVIDER, MarketProviderRun.demand_key == marker_key
        ).first() is not None

    if marked():
        return {"status": "already_ingested_this_slot"}
    with _provider_lock(db, SLOT_MARKER_PROVIDER) as acquired:
        if not acquired:
            return {"status": "in_progress_elsewhere"}
        if marked():
            return {"status": "already_ingested_this_slot"}
        started = datetime.utcnow()
        providers = await ingest_due_demands(db, deadline=deadline, trigger=trigger)
        complete = all(item.get("status") != "deferred_time_budget" for item in providers.values())
        if complete:
            db.add(MarketProviderRun(
                provider=SLOT_MARKER_PROVIDER, demand_key=marker_key, trigger=trigger, status="ok", started_at=started,
                finished_at=datetime.utcnow(), observations_seen=0, points_inserted=0, points_revised=0, duplicates=0,
                trace_json={"providers": {key: value.get("status") for key, value in providers.items()}},
            ))
            db.commit()
        return providers


async def evaluate_organization(db: Session, organization_id: str, *, deadline: float) -> dict[str, Any]:
    positions = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == organization_id, MarketPosition.status == "active")
        .order_by(MarketPosition.updated_at.asc(), MarketPosition.id.asc())
        .all()
    )
    evaluated, failed, events = 0, 0, []
    for position in positions:
        if time.monotonic() > deadline:
            break
        try:
            await refresh_position_market_data(db, position, ingest_missing=False, trigger="scheduled")
            outcome = evaluate_position(db, position)
            db.commit()
            events.extend(outcome.get("events_created") or [])
            evaluated += 1
        except Exception:  # noqa: BLE001 - one bad position must not stop the portfolio
            db.rollback()
            failed += 1
            logger.exception("market_cycle_position_failed position=%s", position.id)
    return {"positions": len(positions), "evaluated": evaluated, "failed": failed, "complete": evaluated + failed == len(positions), "events_created": events}


# ---------------------------------------------------------------------------
# Alert delivery (email explicitly opt-in; attempts tracked per recipient)
# ---------------------------------------------------------------------------

ALERT_WINDOW = timedelta(days=7)
MAX_EMAIL_ATTEMPTS = 5
_DIGEST_COPY = {
    "en": {"subject": "{count} commercial change(s) need your attention", "intro": "AGRO-AI Market Intelligence found material changes to your commercial position:",
           "line": "{level}: {position}", "outro": "Open Market Intelligence to review the evidence and scenarios. This is decision support, not a trading instruction."},
    "pt": {"subject": "{count} mudança(s) comercial(is) exigem sua atenção", "intro": "O AGRO-AI Market Intelligence encontrou mudanças materiais na sua posição comercial:",
           "line": "{level}: {position}", "outro": "Abra o Market Intelligence para revisar as evidências e os cenários. Isto é apoio à decisão, não uma instrução de negociação."},
    "es": {"subject": "{count} cambio(s) comercial(es) requieren su atención", "intro": "AGRO-AI Market Intelligence detectó cambios materiales en su posición comercial:",
           "line": "{level}: {position}", "outro": "Abra Market Intelligence para revisar la evidencia y los escenarios. Esto es apoyo a la decisión, no una instrucción de negociación."},
    "fr": {"subject": "{count} changement(s) commercial(aux) demandent votre attention", "intro": "AGRO-AI Market Intelligence a détecté des changements significatifs de votre position commerciale :",
           "line": "{level} : {position}", "outro": "Ouvrez Market Intelligence pour examiner les preuves et les scénarios. Il s'agit d'une aide à la décision, pas d'une instruction de négociation."},
}


def _recipient_language(db: Session, user_id: str) -> str:
    preference = db.get(UserPreference, user_id)
    locale = str((preference.locale if preference is not None else None) or "en").strip().lower()
    return "en" if locale in {"", "auto"} else locale.split("-")[0]


def _retry_at(now: datetime, attempts: int) -> datetime:
    return now + min(timedelta(hours=12), timedelta(minutes=15) * (2 ** max(0, attempts - 1)))


def _eligible_recipients(db: Session, organization_id: str) -> list[User]:
    """Owners/admins who may receive commercial alerts right now."""
    return (
        db.query(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == "active",
            OrganizationMembership.role.in_(("owner", "admin")),
            User.email_verification_status == "verified",
            # Suspended, restricted or deactivated accounts receive nothing.
            User.is_active.is_(True),
            User.account_status == "active",
            User.access_restricted_at.is_(None),
        )
        .all()
    )


def _ensure_deliveries(db: Session, organization_id: str, *, now: datetime) -> None:
    urgent = (
        db.query(MarketMaterialityEvent)
        .filter(
            MarketMaterialityEvent.organization_id == organization_id,
            MarketMaterialityEvent.status == "open",
            MarketMaterialityEvent.level.in_(("HIGH", "CRITICAL")),
            MarketMaterialityEvent.created_at >= now - ALERT_WINDOW,
        )
        .all()
    )
    if not urgent:
        return
    recipients = _eligible_recipients(db, organization_id)
    existing = {
        (row.event_id, row.user_id)
        for row in db.query(MarketAlertDelivery.event_id, MarketAlertDelivery.user_id).filter(
            MarketAlertDelivery.organization_id == organization_id,
            MarketAlertDelivery.event_id.in_([event.id for event in urgent]),
            MarketAlertDelivery.channel == "email",
        )
    }
    for event in urgent:
        for user in recipients:
            if (event.id, user.id) in existing:
                continue
            language = _recipient_language(db, user.id)
            supported = language in _DIGEST_COPY
            db.add(MarketAlertDelivery(
                organization_id=organization_id,
                event_id=event.id,
                user_id=user.id,
                channel="email",
                language=language,
                # No reviewed template for this language: never send English
                # silently; the alert stays in-app and the deferral is explicit.
                status="pending" if supported else "deferred_unsupported_language",
                attempts=0,
                next_attempt_at=now if supported else None,
            ))
    db.flush()


def cancel_deliveries(db: Session, delivery_ids: list[str]) -> int:
    """Stop pending/retrying deliveries (alert no longer open). Does not commit."""
    if not delivery_ids:
        return 0
    return (
        db.query(MarketAlertDelivery)
        .filter(MarketAlertDelivery.id.in_(delivery_ids), MarketAlertDelivery.status.in_(("pending", "retrying")))
        .update({MarketAlertDelivery.status: "cancelled_alert_closed", MarketAlertDelivery.next_attempt_at: None}, synchronize_session=False)
    )


def cancel_event_deliveries(db: Session, organization_id: str, event_id: str) -> int:
    ids = [row.id for row in db.query(MarketAlertDelivery.id).filter(
        MarketAlertDelivery.organization_id == organization_id, MarketAlertDelivery.event_id == event_id)]
    return cancel_deliveries(db, ids)


def deliver_alerts(db: Session, organization_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Email owners/admins about HIGH/CRITICAL events. Opt-in only.

    A delivery is ``delivered`` only when the email provider accepted it.
    Failures keep the row ``retrying`` with backoff until MAX_EMAIL_ATTEMPTS,
    then ``failed``; every attempt increments ``attempts``.
    """
    if not _flag("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED"):
        return {"status": "disabled"}
    from app.services.email_delivery import send_email

    now = now or datetime.utcnow()
    _ensure_deliveries(db, organization_id, now=now)
    # Deliveries for alerts that were acknowledged or resolved meanwhile stop.
    closed = [
        row.id for row in db.query(MarketAlertDelivery.id)
        .join(MarketMaterialityEvent, MarketMaterialityEvent.id == MarketAlertDelivery.event_id)
        .filter(
            MarketAlertDelivery.organization_id == organization_id,
            MarketAlertDelivery.status.in_(("pending", "retrying")),
            MarketMaterialityEvent.status != "open",
        )
    ]
    if closed:
        cancel_deliveries(db, closed)
    due = (
        db.query(MarketAlertDelivery)
        .join(MarketMaterialityEvent, MarketMaterialityEvent.id == MarketAlertDelivery.event_id)
        .filter(
            MarketMaterialityEvent.status == "open",
            MarketAlertDelivery.organization_id == organization_id,
            MarketAlertDelivery.channel == "email",
            MarketAlertDelivery.status.in_(("pending", "retrying")),
            or_(MarketAlertDelivery.next_attempt_at.is_(None), MarketAlertDelivery.next_attempt_at <= now),
        )
        .all()
    )
    deferred = (
        db.query(func.count(MarketAlertDelivery.id))
        .filter(MarketAlertDelivery.organization_id == organization_id, MarketAlertDelivery.status == "deferred_unsupported_language")
        .scalar()
    )
    if not due:
        db.commit()
        return {"status": "nothing_due", "deferred_unsupported_language": int(deferred or 0)}
    events = {
        event.id: event
        for event in db.query(MarketMaterialityEvent).filter(MarketMaterialityEvent.id.in_({row.event_id for row in due}))
    }
    names = {
        position.id: position.name
        for position in db.query(MarketPosition).filter(MarketPosition.id.in_({event.position_id for event in events.values()}))
    }
    # Re-check eligibility at send time: a recipient suspended, restricted or
    # removed since the delivery was created must not receive retries.
    eligible = {user.id for user in _eligible_recipients(db, organization_id)}
    ineligible = [row for row in due if row.user_id not in eligible]
    for row in ineligible:
        row.status, row.next_attempt_at = "cancelled_recipient_ineligible", None
    due = [row for row in due if row.user_id in eligible]
    by_user: dict[str, list[MarketAlertDelivery]] = {}
    for row in due:
        by_user.setdefault(row.user_id, []).append(row)
    delivered = failed = retrying = 0
    for user_id, rows in by_user.items():
        user = db.get(User, user_id)
        language = rows[0].language if rows[0].language in _DIGEST_COPY else "en"
        copy = _DIGEST_COPY[language]
        lines = [copy["line"].format(level=events[row.event_id].level, position=names.get(events[row.event_id].position_id, "")) for row in rows if row.event_id in events]
        try:
            result = send_email(
                to_email=user.email,
                subject=copy["subject"].format(count=len(lines)),
                text_body="\n".join([copy["intro"], "", *lines, "", copy["outro"]]),
                tags=[{"name": "category", "value": "market_intelligence_alert"}],
            ) if user is not None else {"ok": False, "reason": "recipient_missing"}
        except Exception as exc:  # noqa: BLE001 - a provider exception is a failed attempt, never a success
            result = {"ok": False, "reason": exc.__class__.__name__}
        for row in rows:
            row.attempts = int(row.attempts or 0) + 1
            row.last_attempt_at = now
            if result.get("ok"):
                row.status, row.delivered_at, row.next_attempt_at, row.last_error = "delivered", now, None, None
                delivered += 1
            elif row.attempts >= MAX_EMAIL_ATTEMPTS:
                row.status, row.next_attempt_at, row.last_error = "failed", None, str(result.get("reason") or "send_failed")[:200]
                failed += 1
            else:
                row.status, row.next_attempt_at, row.last_error = "retrying", _retry_at(now, row.attempts), str(result.get("reason") or "send_failed")[:200]
                retrying += 1
    db.commit()
    return {"status": "attempted", "delivered": delivered, "retrying": retrying, "failed": failed, "deferred_unsupported_language": int(deferred or 0)}


# ---------------------------------------------------------------------------
# Job processing (delivered by the Cloudflare Queue consumer)
# ---------------------------------------------------------------------------


def _job_budget() -> float:
    try:
        return max(10.0, float(os.getenv("MARKET_INTELLIGENCE_CYCLE_JOB_BUDGET_SECONDS", "") or DEFAULT_JOB_TIME_BUDGET_SECONDS))
    except ValueError:
        return DEFAULT_JOB_TIME_BUDGET_SECONDS


async def run_organization_cycle(
    db: Session,
    organization_id: str,
    *,
    time_budget_seconds: float | None = None,
    trigger: str = "scheduled",
    slot: str | None = None,
    allow_incomplete_ingestion: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + (time_budget_seconds if time_budget_seconds is not None else _job_budget())
    providers = await ingest_once_per_slot(db, slot or _slot(datetime.utcnow()), deadline=deadline, trigger=trigger)
    barrier_open = providers.get("status") == "already_ingested_this_slot" or (
        "status" not in providers and all(item.get("status") != "deferred_time_budget" for item in providers.values())
    )
    if not barrier_open and not allow_incomplete_ingestion:
        raise SlotIngestionPending(str(providers.get("status") or "ingestion_incomplete"))
    outcome = await evaluate_organization(db, organization_id, deadline=deadline)
    notifications = deliver_alerts(db, organization_id)
    return {
        "organization_id": organization_id,
        "duration_seconds": round(time.monotonic() - started, 2),
        "providers": providers,
        "positions": outcome["positions"],
        "evaluated": outcome["evaluated"],
        "failed_positions": outcome["failed"],
        "complete": outcome["complete"],
        "events_created": len(outcome["events_created"]),
        "notifications": notifications,
        "shared_ingestion_complete": barrier_open,
    }


def _defer_job(db: Session, job_id: str, *, worker_id: str, reason: str) -> str:
    """Re-queue a claimed job without counting an attempt (contention is not failure)."""
    db.rollback()
    now = datetime.utcnow()
    job = db.get(IngestionJob, job_id)
    if job is None or job.status != "running" or job.worker_id != worker_id:
        return "deferred"
    payload = dict(job.input_json or {})
    payload["slot_deferrals"] = int(payload.get("slot_deferrals") or 0) + 1
    payload["last_deferral_reason"] = reason
    job.status = "queued"
    job.attempt_count = max(0, int(job.attempt_count or 1) - 1)
    job.next_attempt_at = now + timedelta(seconds=SLOT_DEFER_SECONDS)
    job.lease_expires_at = None
    job.worker_id = None
    job.input_json = payload
    job.updated_at = now
    state = _state(db, job.tenant_id)
    state.last_status = "waiting_for_shared_ingestion"
    db.commit()
    return "deferred"


def process_market_cycle_job(db: Session, *, job_id: str, organization_id: str, worker_id: str) -> str:
    job = _claim(db, job_id=job_id, tenant_id=organization_id, worker_id=worker_id)
    if job is None:
        return "deferred"  # leased elsewhere or not yet due; the queue redelivers later
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job.status
    if job.job_type != TASK_TYPE:
        raise ValueError("unsupported market intelligence job type")
    # Check before touching per-organization state (it references the
    # organization): a deleted organization or a disabled cycle completes cleanly.
    if db.get(Organization, organization_id) is None or not cycle_enabled():
        return _complete(db, job, {"status": "skipped"}, worker_id=worker_id)
    state = _state(db, organization_id)
    state.last_started_at = datetime.utcnow()
    state.last_job_id = job_id
    state.last_status = "running"
    db.commit()
    with job_lease_heartbeat(job_id=job_id, tenant_id=organization_id, worker_id=worker_id):
        try:
            payload = job.input_json or {}
            output = asyncio.run(run_organization_cycle(
                db, organization_id, trigger=str(payload.get("trigger") or "scheduled"), slot=payload.get("slot"),
                allow_incomplete_ingestion=int(payload.get("slot_deferrals") or 0) >= MAX_SLOT_DEFERRALS,
            ))
        except SlotIngestionPending as pending:
            return _defer_job(db, job_id, worker_id=worker_id, reason=pending.status)
        except Exception as exc:  # noqa: BLE001
            logger.exception("market_cycle_job_failed job=%s", job_id)
            status = _fail_or_retry(db, job_id, exc, worker_id=worker_id)
            state = _state(db, organization_id)
            state.last_status = status
            state.consecutive_failures = int(state.consecutive_failures or 0) + 1
            db.commit()
            return status
    job = db.get(IngestionJob, job_id)
    status = _complete(db, job, output, worker_id=worker_id)
    state = _state(db, organization_id)
    if status == "succeeded":
        state.last_completed_at = datetime.utcnow()
        state.last_status = "succeeded" if output.get("complete") and output.get("shared_ingestion_complete") else "partial"
        state.consecutive_failures = 0
    db.commit()
    return status


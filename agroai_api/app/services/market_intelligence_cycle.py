"""Scheduled Commercial Intelligence cycle.

Runs from the hourly maintenance hook (Cloudflare cron -> drain-outbox), off
the request path, so customers never need to press "refresh":

1. ingest due shared provider demands once for all tenants;
2. re-resolve every active position from the shared plane (no provider calls);
3. snapshot economics and evaluate materiality;
4. notify (in-app always; email digests only when explicitly enabled).

Single-flight: a PostgreSQL advisory lock (or an in-process lock on SQLite)
prevents overlapping cycles across instances. A time budget bounds each run;
unfinished organizations are picked up next hour (oldest refresh first).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.market_intelligence import MarketMaterialityEvent, MarketPosition
from app.models.saas import Organization, OrganizationMembership, User, UserPreference
from app.services import market_data_plane as plane
from app.services.market_data_adapters import ADAPTERS
from app.services.market_intelligence_refresh import refresh_position_market_data
from app.services.market_materiality import evaluate_position

logger = logging.getLogger("agroai.market_cycle")
_LOCK_KEY = 0x4D4B5443594C  # "MKTCYL"
_process_lock = threading.Lock()
DEFAULT_TIME_BUDGET_SECONDS = 1500.0


def _flag(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def cycle_enabled() -> bool:
    raw = str(os.getenv("MARKET_INTELLIGENCE_CYCLE_ENABLED", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _try_lock(db: Session) -> bool:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY}).scalar())
    return True


def _unlock(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})


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
        demand_key = "|".join(sorted({adapter.demand_key(s) for s in selectors}))[:400] or adapter.demand_key({})
        if not plane.provider_due(db, adapter, demand_key):
            results[provider_id] = {"status": "fresh_enough"}
            continue
        try:
            results[provider_id] = await asyncio.wait_for(
                plane.ingest(db, provider_id, selectors, trigger=trigger, adapter=adapter),
                timeout=max(30.0, min(adapter.request_timeout_seconds + 60.0, deadline - time.monotonic())),
            )
        except asyncio.TimeoutError:
            db.rollback()
            results[provider_id] = {"status": "timeout"}
    return results


async def evaluate_organization(db: Session, organization_id: str, *, deadline: float) -> dict[str, Any]:
    positions = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == organization_id, MarketPosition.status == "active")
        .order_by(MarketPosition.updated_at.asc())
        .all()
    )
    evaluated, events = 0, []
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
            logger.exception("market_cycle_position_failed position=%s", position.id)
    return {"positions": len(positions), "evaluated": evaluated, "events_created": events}


# ---------------------------------------------------------------------------
# Email digest foundation (explicitly opt-in).
# ---------------------------------------------------------------------------

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


def _recipient_language(db: Session, user_id: str) -> str | None:
    preference = db.get(UserPreference, user_id)
    locale = str((preference.locale if preference is not None else None) or "en").strip().lower()
    language = "en" if locale in {"", "auto"} else locale.split("-")[0]
    return language if language in _DIGEST_COPY else None


def send_alert_digest(db: Session, organization_id: str, event_ids: list[str]) -> dict[str, Any]:
    """Email owners/admins about new HIGH/CRITICAL events. Opt-in only.

    Recipients whose language has no reviewed digest template are not sent
    English silently; the event stays in-app and the deferral is recorded.
    """
    if not event_ids:
        return {"status": "nothing_to_send"}
    if not _flag("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED"):
        return {"status": "disabled"}
    from app.services.email_delivery import send_email

    events = (
        db.query(MarketMaterialityEvent)
        .filter(MarketMaterialityEvent.organization_id == organization_id, MarketMaterialityEvent.id.in_(event_ids))
        .all()
    )
    urgent = [event for event in events if event.level in {"HIGH", "CRITICAL"} and not (event.notified_json or {}).get("email")]
    if not urgent:
        return {"status": "nothing_urgent"}
    positions = {p.id: p.name for p in db.query(MarketPosition).filter(MarketPosition.id.in_([e.position_id for e in urgent]))}
    recipients = (
        db.query(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == "active",
            OrganizationMembership.role.in_(("owner", "admin")),
            User.email_verification_status == "verified",
        )
        .all()
    )
    sent, deferred = 0, 0
    for user in recipients:
        language = _recipient_language(db, user.id)
        if language is None:
            deferred += 1
            continue
        copy = _DIGEST_COPY[language]
        lines = [copy["line"].format(level=e.level, position=positions.get(e.position_id, "")) for e in urgent]
        result = send_email(
            to_email=user.email,
            subject=copy["subject"].format(count=len(urgent)),
            text_body="\n".join([copy["intro"], "", *lines, "", copy["outro"]]),
            tags=[{"name": "category", "value": "market_intelligence_alert"}],
        )
        sent += 1 if result.get("ok") else 0
    stamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for event in urgent:
        event.notified_json = {**(event.notified_json or {}), "email": {"at": stamp, "sent": sent, "deferred_unsupported_language": deferred}}
    db.commit()
    return {"status": "sent", "recipients": sent, "deferred": deferred}


async def run_cycle(*, time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS, trigger: str = "scheduled") -> dict[str, Any]:
    if not cycle_enabled():
        return {"status": "disabled"}
    if not _process_lock.acquire(blocking=False):
        return {"status": "already_running"}
    started = time.monotonic()
    deadline = started + max(30.0, time_budget_seconds)
    db = SessionLocal()
    locked = False
    try:
        locked = _try_lock(db)
        if not locked:
            return {"status": "already_running_elsewhere"}
        providers = await ingest_due_demands(db, deadline=deadline, trigger=trigger)
        organizations = [row[0] for row in db.query(MarketPosition.organization_id).filter(MarketPosition.status == "active").distinct().all()]
        org_results: dict[str, Any] = {}
        for organization_id in organizations:
            if time.monotonic() > deadline:
                org_results[organization_id] = {"status": "deferred_time_budget"}
                continue
            if db.get(Organization, organization_id) is None:
                continue
            outcome = await evaluate_organization(db, organization_id, deadline=deadline)
            outcome["notifications"] = send_alert_digest(db, organization_id, outcome["events_created"])
            org_results[organization_id] = {**outcome, "events_created": len(outcome["events_created"])}
        return {
            "status": "ok",
            "trigger": trigger,
            "duration_seconds": round(time.monotonic() - started, 2),
            "providers": providers,
            "organizations": len(organizations),
            "organization_results": org_results,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("market_cycle_failed")
        return {"status": "error", "reason": exc.__class__.__name__}
    finally:
        if locked:
            try:
                _unlock(db)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
        db.close()
        _process_lock.release()


def run_cycle_sync(**kwargs: Any) -> dict[str, Any]:
    """Entry point for background tasks running outside an event loop."""
    return asyncio.run(run_cycle(**kwargs))

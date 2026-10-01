"""Lifecycle onboarding email for the AGRO-AI Enterprise Portal.

All campaign logic lives here. Authentication only calls ``enroll_user`` after
a verified account exists; the hourly scheduled maintenance (Cloudflare edge
cron -> /v1/internal/queue/drain-outbox) calls ``process_due``.

Guarantees
- Persistent: sequence position lives in ``lifecycle_email_enrollments`` /
  ``lifecycle_email_sends``; restarts and redeploys never resend.
- Idempotent: one row per (user, step) enforced by a unique constraint; a send
  is claimed by inserting that row (or atomically flipping a retry row), so
  concurrent schedulers cannot both send. A send interrupted mid-flight is
  never retried (it may have been delivered) and is marked ``interrupted``.
- Event-aware: each step is re-evaluated against the customer's real activity
  at send time and skipped (with a recorded reason) when it no longer applies.
- Localized at send time from the user's current preference
  (``lifecycle_email_i18n``); a supported locale never silently gets English.
- Separate from transactional mail: unsubscribe stops only this sequence.
- Safe rollout: nothing is sent unless LIFECYCLE_EMAILS_ENABLED and a footer
  postal address are configured; overdue steps expire instead of bursting.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import Any, Callable
from urllib.parse import urlencode

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.lifecycle_email import LifecycleEmailEnrollment, LifecycleEmailSend
from app.models.saas import Organization, OrganizationMembership, SelfServiceLegalAcceptance, TeamInvitation, UsageEvent, User, UserPreference
from app.services.lifecycle_email_i18n import LifecycleLocalizationUnavailable, localized_copy, resolve_locale

logger = logging.getLogger("agroai.lifecycle_email")

SEQUENCE_VERSION = "2026-10-01.v1"


@dataclass(frozen=True)
class Step:
    key: str
    delay: timedelta
    route: str


# Order matters: one lifecycle email per user per scheduler pass, at most one
# per MIN_GAP. "market" is the production Market Intelligence surface (crop
# positions, contracts, exposure); "team" applies only to plans with invites.
STEPS: tuple[Step, ...] = (
    Step("welcome", timedelta(0), "/onboarding"),
    Step("connect_data", timedelta(days=1), "/integrations"),
    Step("ask", timedelta(days=3), "/intelligence"),
    Step("field", timedelta(days=5), "/field-intelligence"),
    Step("market", timedelta(days=7), "/market-intelligence"),
    Step("connectors", timedelta(days=10), "/integrations"),
    Step("team", timedelta(days=12), "/team"),
    Step("plans", timedelta(days=14), "/billing"),
    Step("reactivation", timedelta(days=21), "/"),
)
STEP_BY_KEY = {step.key: step for step in STEPS}
FINAL = {"sent", "skipped", "failed", "interrupted"}
MIN_GAP = timedelta(hours=20)
EXPIRE_AFTER = timedelta(hours=72)
LOCALIZATION_GIVE_UP = timedelta(days=3)
MAX_ATTEMPTS = 6
SENDING_STALE_AFTER = timedelta(minutes=30)
INACTIVE_AFTER = timedelta(days=7)
PAID_SUBSCRIPTION_STATES = {"active", "trialing", "past_due"}
CONNECTED_STATES = {"connected", "synced", "syncing", "test_passed", "ready"}
ADMIN_ROLES = {"owner", "admin"}


# --------------------------------------------------------------------------
# Activity signals (derived from existing tables; no new analytics system)
# --------------------------------------------------------------------------

@dataclass
class Signals:
    plan: str
    paid: bool
    enterprise: bool
    previous_subscriber: bool
    non_customer: bool
    role: str
    has_data: bool = False
    connector_connected: bool = False
    asked: bool = False
    field_used: bool = False
    market_used: bool = False
    team_invited: bool = False
    team_invites_enabled: bool = False
    ask_enabled: bool = False
    seats: int | None = None
    last_active_at: datetime | None = None
    ai_used_this_month: int = 0
    ai_limit: int | None = None
    uploads_this_month: int = 0
    upload_limit: int | None = None
    activation_times: dict[str, datetime] = field(default_factory=dict)


def _first(db: Session, model: Any, *criteria: Any, column: str = "created_at") -> datetime | None:
    col = getattr(model, column, None)
    if col is None:
        return None
    return db.query(func.min(col)).filter(*criteria).scalar()


def gather_signals(db: Session, user: User, org: Organization) -> Signals:
    from app.models.field_intelligence import FieldObservation
    from app.models.market_intelligence import MarketPosition
    from app.models.operational_records import ChatConversation, ConnectorConnection, DataSource, IntelligenceRun
    from app.services.commercial_control import resolve_effective_entitlements
    from app.services.non_customer_access import access_profile_metadata

    plan = str(org.plan or "free").lower()
    plan = {"pilot": "free", "pro": "professional", "waterops": "professional", "assurance_audit": "professional", "assurance": "team"}.get(plan, plan)
    paid = plan != "free" and str(org.subscription_status or "").lower() in PAID_SUBSCRIPTION_STATES
    membership = db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=user.id).first()
    # Effective entitlements (plan, contract overrides, inactive subscriptions):
    # emails never invite a customer to something their plan does not include.
    effective = resolve_effective_entitlements(db, org)
    signals = Signals(
        plan=plan if paid else "free",
        paid=paid,
        enterprise=plan == "enterprise" or bool(getattr(org, "is_enterprise", False)),
        previous_subscriber=bool(getattr(org, "stripe_subscription_id", None)) and not paid,
        non_customer=access_profile_metadata(org)["profile"] != "customer",
        role=str(getattr(membership, "role", "") or ""),
        team_invites_enabled=effective.state("team.invite") == "enabled",
        ask_enabled=effective.state("intelligence.ask") in {"enabled", "preview"},
        seats=effective.value("quota.seat"),
        ai_limit=effective.value("quota.ai_action.monthly"),
        upload_limit=effective.value("quota.evidence_upload.monthly"),
    )
    t = signals.activation_times
    data_at = [
        _first(db, DataSource, DataSource.tenant_id == org.id),
        _first(db, ConnectorConnection, ConnectorConnection.tenant_id == org.id, ConnectorConnection.status.in_(CONNECTED_STATES)),
    ]
    data_at = [value for value in data_at if value]
    if data_at:
        signals.has_data, t["has_data"] = True, min(data_at)
    connected = _first(db, ConnectorConnection, ConnectorConnection.tenant_id == org.id, ConnectorConnection.status.in_(CONNECTED_STATES))
    if connected:
        signals.connector_connected, t["connector_connected"] = True, connected
    asked_at = [
        _first(db, ChatConversation, ChatConversation.tenant_id == org.id),
        _first(db, IntelligenceRun, IntelligenceRun.tenant_id == org.id, ~IntelligenceRun.run_type.like("%report%")),
        _first(db, UsageEvent, UsageEvent.organization_id == org.id, UsageEvent.metric == "ai_action"),
    ]
    asked_at = [value for value in asked_at if value]
    if asked_at:
        signals.asked, t["asked"] = True, min(asked_at)
    field_at = _first(db, FieldObservation, FieldObservation.tenant_id == org.id)
    if field_at:
        signals.field_used, t["field_used"] = True, field_at
    market_at = _first(db, MarketPosition, MarketPosition.organization_id == org.id)
    if market_at:
        signals.market_used, t["market_used"] = True, market_at
    invited_at = _first(db, TeamInvitation, TeamInvitation.organization_id == org.id)
    if invited_at:
        signals.team_invited, t["team_invited"] = True, invited_at
    signals.last_active_at = user.last_login_at
    from app.services.quota import committed_usage

    signals.ai_used_this_month = committed_usage(db, org, "ai_action")
    signals.uploads_this_month = committed_usage(db, org, "evidence_upload")
    return signals


# --------------------------------------------------------------------------
# Step rules
# --------------------------------------------------------------------------

@dataclass
class Decision:
    send: bool
    reason: str | None = None
    variant: str | None = None


def _next_unfinished(signals: Signals) -> str | None:
    if not signals.has_data:
        return "connect_data"
    if not signals.asked and signals.ask_enabled:
        return "ask"
    if not signals.field_used:
        return "field"
    if not signals.market_used:
        return "market"
    return None


def evaluate(step: str, signals: Signals, now: datetime) -> Decision:
    if signals.non_customer:
        return Decision(False, "non_customer_profile")
    if step == "welcome":
        return Decision(True)
    if step == "connect_data":
        return Decision(False, "already_connected_data") if signals.has_data else Decision(True)
    if step == "ask":
        if not signals.ask_enabled:
            return Decision(False, "not_in_plan")
        if signals.asked:
            return Decision(False, "already_asked")
        return Decision(True, variant="with_data" if signals.has_data else "without_data")
    if step == "field":
        return Decision(False, "already_used_field_intelligence") if signals.field_used else Decision(True)
    if step == "market":
        return Decision(False, "already_used_market_intelligence") if signals.market_used else Decision(True)
    if step == "connectors":
        if signals.connector_connected:
            return Decision(False, "already_connected_system")
        return Decision(True, variant="paid" if signals.paid else "free")
    if step == "team":
        if not signals.team_invites_enabled:
            return Decision(False, "plan_without_team_invites")
        if signals.role not in ADMIN_ROLES:
            return Decision(False, "not_an_admin")
        return Decision(False, "already_invited_team") if signals.team_invited else Decision(True)
    if step == "plans":
        if signals.paid:
            return Decision(False, "paid_plan")
        if signals.enterprise:
            return Decision(False, "enterprise_customer")
        if signals.previous_subscriber:
            return Decision(False, "previous_subscriber")
        if signals.role not in ADMIN_ROLES:
            return Decision(False, "not_an_admin")
        upload_limit = signals.upload_limit
        near_limit = bool(upload_limit and signals.uploads_this_month >= 0.8 * upload_limit)
        return Decision(True, variant="usage" if near_limit else "standard")
    if step == "reactivation":
        next_step = _next_unfinished(signals)
        recently_active = signals.last_active_at is not None and now - signals.last_active_at < INACTIVE_AFTER
        if next_step is None:
            return Decision(False, "fully_activated")
        if recently_active:
            return Decision(False, "recently_active")
        return Decision(True, variant=next_step)
    return Decision(False, "unknown_step")


ACTIVATION_FOR_STEP = {
    "connect_data": "has_data",
    "ask": "asked",
    "field": "field_used",
    "market": "market_used",
    "connectors": "connector_connected",
    "team": "team_invited",
}


# --------------------------------------------------------------------------
# Unsubscribe links (lifecycle sequence only)
# --------------------------------------------------------------------------

def _unsubscribe_key() -> bytes:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), b"agroai-lifecycle-unsubscribe-v1", hashlib.sha256).digest()


def unsubscribe_token(user_id: str) -> str:
    digest = hmac.new(_unsubscribe_key(), user_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:24]).decode("ascii").rstrip("=")


def verify_unsubscribe_token(user_id: str, token: str) -> bool:
    return bool(user_id and token) and hmac.compare_digest(unsubscribe_token(user_id), token)


def portal_origin() -> str:
    from app.services.email_verification import verification_base_url

    return verification_base_url().rstrip("/")


def unsubscribe_url(user_id: str) -> str:
    return f"{portal_origin()}/v1/email/lifecycle/unsubscribe?{urlencode({'u': user_id, 't': unsubscribe_token(user_id)})}"


def unsubscribe(db: Session, user_id: str, *, source: str) -> bool:
    enrollment = db.get(LifecycleEmailEnrollment, user_id)
    if enrollment is None:
        enrollment = LifecycleEmailEnrollment(user_id=user_id, sequence_version=SEQUENCE_VERSION, source="unsubscribe", enrolled_at=datetime.utcnow())
        db.add(enrollment)
    if enrollment.unsubscribed_at is None:
        enrollment.unsubscribed_at = datetime.utcnow()
    _stop(enrollment, "unsubscribed")
    db.commit()
    logger.info("lifecycle_email_unsubscribed user_id=%s source=%s", user_id, source)
    return True


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _fmt(template: str, values: dict[str, Any]) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_Safe({k: "" if v is None else v for k, v in values.items()}))


def available_connector_names() -> list[str]:
    from app.api.v1.connectors import CATALOG
    from app.services.connector_availability import COMING_SOON_PROVIDERS

    names = []
    for item in CATALOG:
        if item.get("id") in COMING_SOON_PROVIDERS or item.get("status") == "coming_soon":
            continue
        if item.get("id") in {"chat_upload", "custom_api", "universal_controller"}:
            continue
        names.append(str(item.get("name")))
    return names


def _number(value: Any, locale: str) -> str:
    if value is None:
        return "∞"
    try:
        from babel.numbers import format_decimal  # type: ignore

        return format_decimal(int(value), locale=locale.replace("-", "_"))
    except Exception:
        return f"{int(value):,}" if isinstance(value, int) else str(value)


def render(step: str, variant: str | None, copy: dict[str, str], *, locale: str, user: User, org: Organization, signals: Signals) -> dict[str, str]:
    from app.services.commercial_control import BASE_ENTITLEMENTS

    free, pro = BASE_ENTITLEMENTS["free"], BASE_ENTITLEMENTS["professional"]
    from app.services.lifecycle_email_i18n import product_labels

    values = {
        **product_labels(locale),
        "name": (user.name or "").strip(),
        "organization": org.name,
        "connectors": ", ".join(available_connector_names()),
        "seats": _number(signals.seats, locale),
        "pro_messages": _number(pro.get("quota.ai_action.monthly"), locale),
        "free_uploads": _number(free.get("quota.evidence_upload.monthly"), locale),
        "pro_uploads": _number(pro.get("quota.evidence_upload.monthly"), locale),
        "pro_workspaces": _number(pro.get("quota.workspace"), locale),
        "pro_seats": _number(pro.get("quota.seat"), locale),
        "used": _number(signals.uploads_this_month, locale),
        "limit": _number(signals.upload_limit, locale),
    }
    c = lambda key: _fmt(copy[key], values)  # noqa: E731
    prefix = {"connect_data": "connect_data", "reactivation": "reactivation"}.get(step, step)
    paragraphs: list[str] = []
    bullets: list[str] = []
    cta_step = step
    if step == "welcome":
        paragraphs = [c("welcome.body1"), c("welcome.body2")]
    elif step == "connect_data":
        paragraphs = [c("connect_data.body1"), c("connect_data.body2")]
    elif step == "ask":
        paragraphs = [c("ask.body1")]
        bullets = [c("ask.example1"), c("ask.example2"), c("ask.example3")]
        paragraphs_after = [c("ask.body_with_data" if variant == "with_data" else "ask.body_without_data")]
    elif step == "field":
        paragraphs = [c("field.body1"), c("field.body2")]
    elif step == "market":
        paragraphs = [c("market.body1"), c("market.body2")]
    elif step == "connectors":
        paragraphs = [c("connectors.body1"), c("connectors.available"), c("connectors.body_paid" if variant == "paid" else "connectors.body_free")]
    elif step == "team":
        paragraphs = [c("team.body1")]
    elif step == "plans":
        paragraphs = [c("plans.body1")]
        bullets = [c("plans.item_ask"), c("plans.item_uploads"), c("plans.item_workspaces"), c("plans.item_connectors"), c("plans.item_reports")]
        paragraphs_after = ([c("plans.usage_note")] if variant == "usage" else []) + [c("plans.body2")]
    elif step == "reactivation":
        next_key = {"connect_data": "reactivation.next_connect_data", "ask": "reactivation.next_ask", "field": "reactivation.next_field", "market": "reactivation.next_market"}[variant or "connect_data"]
        paragraphs = [c("reactivation.body1")]
        bullets = [c(next_key)]
        cta_step = variant or "connect_data"
    if step not in {"ask", "plans"}:
        paragraphs_after = []
    route = STEP_BY_KEY[cta_step].route
    cta_key = {"connect_data": "connect_data.cta", "ask": "ask.cta", "field": "field.cta", "market": "market.cta"}.get(cta_step, f"{prefix}.cta")
    query = urlencode({"lang": locale, "utm_source": "agroai", "utm_medium": "email", "utm_campaign": f"lifecycle_{step}"})
    url = f"{portal_origin()}{route}?{query}"
    subject = c(f"{prefix}.subject")
    preview = c(f"{prefix}.preview")
    greeting = c("common.greeting") if values["name"] else c("common.greeting_generic")
    unsub = unsubscribe_url(user.id)
    address = settings.LIFECYCLE_EMAIL_POSTAL_ADDRESS.strip()
    html = _html(locale=locale, preview=preview, headline=c(f"{prefix}.headline"), greeting=greeting, paragraphs=paragraphs,
                 bullets=bullets, after=paragraphs_after, cta=c(cta_key), url=url, fallback=c("common.button_fallback"),
                 signoff=c("common.signoff"), reason=c("common.reason"), unsubscribe=c("common.unsubscribe"),
                 unsubscribe_note=c("common.unsubscribe_note"), unsubscribe_url=unsub, company=c("common.company"), address=address)
    text_lines = [greeting, "", *paragraphs, *(f"- {b}" for b in bullets), *paragraphs_after, "", f"{c(cta_key)}: {url}", "", c("common.signoff"), "", "--", c("common.reason"), f"{c('common.unsubscribe')}: {unsub}", c("common.unsubscribe_note"), c("common.company"), address]
    return {"subject": subject, "preview": preview, "html": html, "text": "\n".join(line for line in text_lines if line is not None).strip() + "\n", "url": url, "unsubscribe_url": unsub}


def _html(*, locale: str, preview: str, headline: str, greeting: str, paragraphs: list[str], bullets: list[str], after: list[str],
          cta: str, url: str, fallback: str, signoff: str, reason: str, unsubscribe: str, unsubscribe_note: str,
          unsubscribe_url: str, company: str, address: str) -> str:
    from app.services.language_registry import family_direction

    e = lambda value: escape(value, quote=True)  # noqa: E731
    direction = "rtl" if family_direction(locale.split("-", 1)[0]) == "rtl" else "ltr"
    align = "right" if direction == "rtl" else "left"
    p = "".join(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6;">{e(x)}</p>' for x in paragraphs)
    b = "".join(f'<li style="margin:0 0 8px;">{e(x)}</li>' for x in bullets)
    blist = f'<ul style="margin:0 0 18px;padding-{align}:20px;font-size:15px;line-height:1.6;">{b}</ul>' if bullets else ""
    a = "".join(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6;">{e(x)}</p>' for x in after)
    return f"""<!doctype html>
<html lang="{e(locale)}" dir="{direction}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(headline)}</title></head>
<body style="margin:0;background:#f6f3ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#10231b;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{e(preview)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f3ea;padding:40px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;border:1px solid #e5e0d6;overflow:hidden;text-align:{align};" dir="{direction}">
<tr><td style="background:#082f23;padding:28px 32px;color:#ffffff;"><div style="font-size:13px;letter-spacing:0.18em;text-transform:uppercase;color:#d9f99d;font-weight:700;">AGRO-AI</div><h1 style="margin:14px 0 0;font-size:24px;line-height:1.3;font-weight:750;">{e(headline)}</h1></td></tr>
<tr><td style="padding:32px;"><p style="margin:0 0 16px;font-size:16px;line-height:1.6;">{e(greeting)}</p>{p}{blist}{a}
<table role="presentation" cellspacing="0" cellpadding="0" style="margin:24px 0;"><tr><td align="center" style="border-radius:10px;background:#0b3326;"><a href="{e(url)}" style="display:inline-block;padding:14px 28px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;border-radius:10px;">{e(cta)}</a></td></tr></table>
<p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#637267;">{e(fallback)}</p>
<p style="word-break:break-all;margin:0 0 24px;font-size:13px;line-height:1.6;"><a href="{e(url)}" style="color:#0b6b43;">{e(url)}</a></p>
<p style="margin:0;font-size:15px;line-height:1.6;">{e(signoff)}</p></td></tr>
<tr><td style="padding:22px 32px;background:#faf8f1;border-top:1px solid #e5e0d6;color:#7a857d;font-size:12px;line-height:1.6;text-align:center;">{e(reason)}<br><a href="{e(unsubscribe_url)}" style="color:#7a857d;">{e(unsubscribe)}</a> &middot; {e(unsubscribe_note)}<br>{e(company)}{"<br>" + e(address) if address else ""}</td></tr>
</table></td></tr></table></body></html>"""


# --------------------------------------------------------------------------
# Enrollment and scheduling
# --------------------------------------------------------------------------

def enroll_user(db: Session, user_id: str, organization_id: str | None, *, source: str, enrolled_at: datetime | None = None) -> LifecycleEmailEnrollment:
    existing = db.get(LifecycleEmailEnrollment, user_id)
    if existing is not None:
        return existing
    row = LifecycleEmailEnrollment(
        user_id=user_id, organization_id=organization_id, sequence_version=SEQUENCE_VERSION,
        source=source, status="active", enrolled_at=enrolled_at or datetime.utcnow(),
    )
    row.next_action_at = row.enrolled_at
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        found = db.get(LifecycleEmailEnrollment, user_id)
        if found is None:
            raise
        return found
    db.commit()
    logger.info("lifecycle_email_enrolled user_id=%s source=%s", user_id, source)
    return row


def _stop(enrollment: LifecycleEmailEnrollment, reason: str) -> None:
    if enrollment.status != "stopped":
        enrollment.status = "stopped"
        enrollment.stop_reason = reason
        enrollment.stopped_at = datetime.utcnow()


def sending_ready() -> str | None:
    """Why lifecycle sending is held, or None when it may send."""
    if not settings.LIFECYCLE_EMAILS_ENABLED:
        return "disabled"
    if not settings.LIFECYCLE_EMAIL_POSTAL_ADDRESS.strip():
        return "postal_address_not_configured"
    return None


def _user_locale(db: Session, user: User) -> str:
    preference = db.get(UserPreference, user.id)
    signup = (
        db.query(SelfServiceLegalAcceptance.locale)
        .filter(SelfServiceLegalAcceptance.user_id == user.id)
        .order_by(SelfServiceLegalAcceptance.accepted_at.desc())
        .first()
    )
    return resolve_locale(getattr(preference, "locale", None), signup[0] if signup else None)


def _record(db: Session, enrollment: LifecycleEmailEnrollment, step: Step, status: str, reason: str | None, now: datetime) -> None:
    row = LifecycleEmailSend(
        user_id=enrollment.user_id, organization_id=enrollment.organization_id, step=step.key,
        status=status, reason=reason, scheduled_for=enrollment.enrolled_at + step.delay,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return
    logger.info("lifecycle_email_%s user_id=%s step=%s reason=%s", status, enrollment.user_id, step.key, reason)


def _attribute_activation(db: Session, enrollment: LifecycleEmailEnrollment, signals: Signals) -> None:
    rows = db.query(LifecycleEmailSend).filter(
        LifecycleEmailSend.user_id == enrollment.user_id, LifecycleEmailSend.status == "sent", LifecycleEmailSend.activated_at.is_(None)
    ).all()
    for row in rows:
        signal = ACTIVATION_FOR_STEP.get(row.step)
        if row.step == "plans":
            if signals.paid:
                row.activation_event, row.activated_at = "subscription_started", datetime.utcnow()
            continue
        if row.step in {"welcome", "reactivation"}:
            if signals.last_active_at and row.sent_at and signals.last_active_at > row.sent_at:
                row.activation_event, row.activated_at = "returned_to_portal", signals.last_active_at
            continue
        when = signals.activation_times.get(signal or "")
        if when and row.sent_at and when >= row.sent_at:
            row.activation_event, row.activated_at = signal, when


def _claim(db: Session, enrollment: LifecycleEmailEnrollment, step: Step, existing: LifecycleEmailSend | None, now: datetime) -> LifecycleEmailSend | None:
    if existing is None:
        row = LifecycleEmailSend(
            user_id=enrollment.user_id, organization_id=enrollment.organization_id, step=step.key,
            status="sending", scheduled_for=enrollment.enrolled_at + step.delay, attempts=1,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            return None  # another scheduler owns this step
        db.commit()
        return row
    claimed = db.execute(
        update(LifecycleEmailSend)
        .where(LifecycleEmailSend.id == existing.id, LifecycleEmailSend.status.in_(["retry", "deferred_localization"]),
               LifecycleEmailSend.attempts == existing.attempts)
        .values(status="sending", attempts=existing.attempts + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if claimed != 1:
        return None
    db.refresh(existing)
    return existing


def _send_step(db: Session, enrollment: LifecycleEmailEnrollment, step: Step, decision: Decision, user: User, org: Organization,
               signals: Signals, existing: LifecycleEmailSend | None, now: datetime, sender: Callable[..., dict]) -> str:
    row = _claim(db, enrollment, step, existing, now)
    if row is None:
        return "claimed_elsewhere"
    locale = _user_locale(db, user)
    row.locale, row.plan_at_send, row.variant = locale, signals.plan, decision.variant
    try:
        copy, how = localized_copy(locale)
    except LifecycleLocalizationUnavailable as exc:
        first = row.created_at or now
        if now - first >= LOCALIZATION_GIVE_UP:
            row.status, row.reason = "skipped", "localization_unavailable"
            logger.error("lifecycle_email_localization_gave_up user_id=%s step=%s locale=%s", user.id, step.key, locale)
        else:
            row.status, row.reason, row.next_attempt_at = "deferred_localization", str(exc)[:120], now + timedelta(hours=1)
            logger.error("lifecycle_email_localization_deferred user_id=%s step=%s locale=%s", user.id, step.key, locale)
        db.commit()
        return row.status
    message = render(step.key, decision.variant, copy, locale=locale, user=user, org=org, signals=signals)
    try:
        result = sender(
            to_email=user.email, subject=message["subject"], text_body=message["text"], html_body=message["html"],
            headers={
                "List-Unsubscribe": f"<{message['unsubscribe_url']}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
            tags=[{"name": "category", "value": "lifecycle"}, {"name": "step", "value": step.key}],
        )
    except Exception as exc:  # pragma: no cover - send_email contains provider errors
        result = {"ok": False, "reason": exc.__class__.__name__}
    if result.get("ok"):
        row.status, row.reason, row.sent_at, row.provider = "sent", None, datetime.utcnow(), result.get("provider")
        row.provider_message_id = _provider_message_id(result)
        enrollment.last_sent_at = row.sent_at
        logger.info("lifecycle_email_sent user_id=%s step=%s locale=%s via=%s plan=%s", user.id, step.key, locale, how, signals.plan)
    else:
        reason = str(result.get("reason") or "provider_failed").split(":", 1)[0][:120]
        permanent = result.get("status_code") in {400, 403, 422}
        if permanent or row.attempts >= MAX_ATTEMPTS:
            row.status, row.reason = "failed", reason
        else:
            backoff = timedelta(hours=6) if reason == "email_provider_not_configured" else timedelta(minutes=30 * 2 ** (row.attempts - 1))
            row.status, row.reason, row.next_attempt_at = "retry", reason, now + backoff
        logger.error("lifecycle_email_not_sent user_id=%s step=%s reason=%s attempts=%s", user.id, step.key, reason, row.attempts)
    db.commit()
    return row.status


def _provider_message_id(result: dict) -> str | None:
    raw = result.get("provider_response")
    try:
        value = json.loads(raw).get("id") if isinstance(raw, str) else None
    except (ValueError, AttributeError):
        value = None
    return str(value)[:200] if value else None


def next_action_time(enrollment: LifecycleEmailEnrollment, rows: dict[str, LifecycleEmailSend]) -> datetime | None:
    """When this enrollment next has work: the first unfinished step's due time,
    no earlier than its retry time or the end of the minimum gap. None when the
    enrollment is no longer active. Mirrors the checks in process_enrollment."""
    if enrollment.status != "active":
        return None
    for step in STEPS:
        row = rows.get(step.key)
        if row is not None and row.status in FINAL:
            continue
        if row is not None and row.status == "sending":
            # Re-examine once a claim would count as stale.
            return (row.updated_at or enrollment.enrolled_at) + SENDING_STALE_AFTER
        candidates = [enrollment.enrolled_at + step.delay]
        if row is not None and row.next_attempt_at:
            candidates.append(row.next_attempt_at)
        if enrollment.last_sent_at:
            candidates.append(enrollment.last_sent_at + MIN_GAP)
        return max(candidates)
    # Every step is final: the next pass marks the enrollment completed.
    return enrollment.enrolled_at


def _schedule_next(db: Session, enrollment: LifecycleEmailEnrollment) -> None:
    rows = {row.step: row for row in db.query(LifecycleEmailSend).filter(LifecycleEmailSend.user_id == enrollment.user_id).all()}
    enrollment.next_action_at = next_action_time(enrollment, rows)
    db.commit()


def process_enrollment(db: Session, enrollment: LifecycleEmailEnrollment, now: datetime | None = None, sender: Callable[..., dict] | None = None) -> str:
    """Advance one user's sequence by at most one email, then record when it next has work."""
    outcome = _advance(db, enrollment, now=now, sender=sender)
    _schedule_next(db, enrollment)
    return outcome


def _advance(db: Session, enrollment: LifecycleEmailEnrollment, now: datetime | None = None, sender: Callable[..., dict] | None = None) -> str:
    from app.services.email_delivery import send_email

    now = now or datetime.utcnow()
    sender = sender or send_email
    if enrollment.status != "active":
        return "inactive"
    user = db.get(User, enrollment.user_id)
    if user is None:
        _stop(enrollment, "user_deleted")
        db.commit()
        return "stopped"
    if enrollment.unsubscribed_at is not None:
        _stop(enrollment, "unsubscribed")
        db.commit()
        return "stopped"
    if str(user.account_status or "active") != "active":
        _stop(enrollment, "account_inactive")
        db.commit()
        return "stopped"
    org = db.get(Organization, enrollment.organization_id) if enrollment.organization_id else None
    if org is None:
        _stop(enrollment, "organization_missing")
        db.commit()
        return "stopped"
    signals = gather_signals(db, user, org)
    _attribute_activation(db, enrollment, signals)
    rows = {row.step: row for row in db.query(LifecycleEmailSend).filter(LifecycleEmailSend.user_id == user.id).all()}
    for row in rows.values():
        if row.status == "sending" and row.updated_at and now - row.updated_at > SENDING_STALE_AFTER:
            row.status, row.reason = "interrupted", "send_interrupted_not_retried"
    db.commit()
    for step in STEPS:
        row = rows.get(step.key)
        if row is not None and row.status in FINAL:
            continue
        if row is not None and row.status == "sending":
            return "in_flight"
        due = enrollment.enrolled_at + step.delay
        if now < due:
            return "waiting"
        if row is not None and row.next_attempt_at and row.next_attempt_at > now:
            return "waiting_retry"
        if enrollment.last_sent_at and now - enrollment.last_sent_at < MIN_GAP:
            return "waiting_gap"
        if row is None and now - due > EXPIRE_AFTER:
            _record(db, enrollment, step, "skipped", "expired", now)
            db.commit()
            continue
        decision = evaluate(step.key, signals, now)
        if not decision.send:
            if row is not None:
                row.status, row.reason = "skipped", decision.reason
            else:
                _record(db, enrollment, step, "skipped", decision.reason, now)
            db.commit()
            continue
        return _send_step(db, enrollment, step, decision, user, org, signals, row, now, sender)
    enrollment.status = "completed"
    db.commit()
    return "completed"


ERROR_BACKOFF = timedelta(hours=1)


def process_due(db: Session, *, now: datetime | None = None, limit: int = 200, sender: Callable[..., dict] | None = None) -> dict[str, Any]:
    """Process enrollments that have work due now, the longest-waiting first.

    Users merely waiting for a later step are not selected, so they cannot fill
    the batch. Each processed enrollment moves its next_action_at forward (the
    next step, the 20h gap, a retry, or ERROR_BACKOFF after a failure), so the
    queue rotates and every due enrollment is reached within a bounded number
    of runs. NULL (pre-039 rows) counts as due at enrollment time.
    """
    held = sending_ready()
    if held:
        return {"status": "held", "reason": held}
    now = now or datetime.utcnow()
    outcomes: dict[str, int] = {}
    due_at = func.coalesce(LifecycleEmailEnrollment.next_action_at, LifecycleEmailEnrollment.enrolled_at)
    enrollments = (
        db.query(LifecycleEmailEnrollment)
        .filter(LifecycleEmailEnrollment.status == "active", due_at <= now)
        .order_by(due_at.asc(), LifecycleEmailEnrollment.user_id.asc())
        .limit(limit)
        .all()
    )
    for enrollment in enrollments:
        user_id = enrollment.user_id
        try:
            outcome = process_enrollment(db, enrollment, now=now, sender=sender)
        except Exception:
            db.rollback()
            logger.exception("lifecycle_email_processing_failed user_id=%s", user_id)
            outcome = "error"
            # Back off so one failing enrollment cannot hold the head of the queue.
            try:
                db.execute(
                    update(LifecycleEmailEnrollment)
                    .where(LifecycleEmailEnrollment.user_id == user_id)
                    .values(next_action_at=now + ERROR_BACKOFF)
                    .execution_options(synchronize_session=False)
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("lifecycle_email_backoff_failed user_id=%s", user_id)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {"status": "ok", "processed": len(enrollments), "outcomes": outcomes}


def _new_session() -> Session:
    if _session_factory is not None:
        return _session_factory()
    from app.db.base import SessionLocal

    return SessionLocal()


# Tests point background hooks at their database; production uses SessionLocal.
_session_factory: Callable[[], Session] | None = None


def enroll_and_start(user_id: str, *, source: str) -> None:
    """Background hook after a verified account exists. Never raises."""
    db = _new_session()
    try:
        user = db.get(User, user_id)
        if user is None:
            return
        membership = (
            db.query(OrganizationMembership)
            .filter(OrganizationMembership.user_id == user_id)
            .order_by(OrganizationMembership.created_at.asc())
            .first()
        )
        enrollment = enroll_user(db, user_id, membership.organization_id if membership else None, source=source)
        if sending_ready() is None:
            process_enrollment(db, enrollment)
    except Exception:
        db.rollback()
        logger.exception("lifecycle_email_enrollment_failed user_id=%s", user_id)
    finally:
        db.close()


def run_scheduled() -> dict[str, Any]:
    """Entry point for the hourly scheduled maintenance."""
    db = _new_session()
    try:
        return process_due(db)
    finally:
        db.close()


def describe(db: Session, user_id: str) -> dict[str, Any]:
    """Engineering view: sequence state, history and the next step (never customer-facing)."""
    enrollment = db.get(LifecycleEmailEnrollment, user_id)
    if enrollment is None:
        return {"enrolled": False}
    rows = db.query(LifecycleEmailSend).filter(LifecycleEmailSend.user_id == user_id).all()
    by_step = {row.step: row for row in rows}
    history = [
        {
            "step": row.step, "status": row.status, "reason": row.reason, "variant": row.variant,
            "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None, "locale": row.locale,
            "plan_at_send": row.plan_at_send, "attempts": row.attempts, "delivered_at": _iso(row.delivered_at),
            "opened_at": _iso(row.opened_at), "clicked_at": _iso(row.clicked_at), "bounced_at": _iso(row.bounced_at),
            "activation_event": row.activation_event, "activated_at": _iso(row.activated_at),
        }
        for step in STEPS if (row := by_step.get(step.key))
    ]
    upcoming = next(
        ({"step": step.key, "due": (enrollment.enrolled_at + step.delay).isoformat()} for step in STEPS
         if by_step.get(step.key) is None or by_step[step.key].status not in FINAL),
        None,
    )
    return {
        "enrolled": True, "status": enrollment.status, "stop_reason": enrollment.stop_reason, "source": enrollment.source,
        "sequence_version": enrollment.sequence_version, "enrolled_at": _iso(enrollment.enrolled_at),
        "unsubscribed": enrollment.unsubscribed_at is not None, "unsubscribed_at": _iso(enrollment.unsubscribed_at),
        "next": upcoming if enrollment.status == "active" else None, "next_action_at": _iso(enrollment.next_action_at), "history": history, "sending": sending_ready() or "ready",
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None

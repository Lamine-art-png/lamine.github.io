"""Purpose-separated Platform API billing and Stripe lifecycle."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.core.config import settings
from app.core.metrics import platform_billing_events
from app.db.base import get_db
from app.models.platform_product import (
    PlatformApiOperationCost,
    PlatformApiPlan,
    PlatformApiSubscription,
    PlatformCreditReservation,
    PlatformStripeEvent,
    PlatformStripeMeterOutbox,
)
from app.models.platform_api import PlatformApiUsageEvent
from app.models.saas import Organization
from app.platform_api.deps import require_developer_control_plane
from app.platform_api.checkout_idempotency import (
    claim_checkout,
    complete_checkout,
    fail_checkout,
    stripe_checkout_idempotency_key,
)
from app.platform_api.product_audit import record_product_audit
from app.platform_api.notifications import notify_subscription_state
from app.platform_api.stripe_metering import publish_pending_meter_outbox
from app.platform_api.programs import active_enrollments
from app.platform_api.stripe_mode import (
    platform_stripe_configuration_error,
    platform_stripe_livemode_matches,
)

router = APIRouter(prefix="/platform", tags=["platform-billing"])


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str
    billing_interval: str

    @field_validator("billing_interval")
    @classmethod
    def interval(cls, value: str) -> str:
        if value not in {"monthly", "annual"}:
            raise ValueError("billing interval must be monthly or annual")
        return value


class CatalogActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_version: str = Field(min_length=1, max_length=120)
    active: bool
    reason: str = Field(min_length=3, max_length=2000)


class AdminBillingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)


def _flag(name: str) -> None:
    if not bool(getattr(settings, name, False)):
        raise HTTPException(status_code=404, detail="Not found")


def _stripe() -> None:
    if not settings.PLATFORM_API_STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail={"code": "api_billing_stripe_not_configured"})
    configuration_error = platform_stripe_configuration_error(
        mode=settings.PLATFORM_API_STRIPE_MODE,
        secret_key=settings.PLATFORM_API_STRIPE_SECRET_KEY,
    )
    if configuration_error:
        raise HTTPException(status_code=503, detail={"code": configuration_error})
    stripe.api_key = settings.PLATFORM_API_STRIPE_SECRET_KEY


def _active_plan(db: Session, identifier: str) -> PlatformApiPlan:
    row = (
        db.query(PlatformApiPlan)
        .filter(
            PlatformApiPlan.catalog_version == settings.PLATFORM_API_PLAN_CATALOG_VERSION,
            PlatformApiPlan.plan_identifier == identifier,
            PlatformApiPlan.active.is_(True),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "api_plan_not_available"})
    return row


def _price_for(plan: PlatformApiPlan, interval: str) -> str:
    config_key = plan.stripe_monthly_price_config_key if interval == "monthly" else plan.stripe_annual_price_config_key
    value = str(getattr(settings, config_key, "") or "").strip() if config_key else ""
    if not value:
        raise HTTPException(status_code=503, detail={"code": "api_plan_price_not_configured"})
    return value


def _overage_price_for(plan: PlatformApiPlan) -> str | None:
    if not plan.overages_allowed:
        return None
    config_key = plan.stripe_overage_price_config_key
    value = str(getattr(settings, config_key, "") or "").strip() if config_key else ""
    if not value:
        raise HTTPException(status_code=503, detail={"code": "api_plan_overage_price_not_configured"})
    return value


def _subscription_public(row: PlatformApiSubscription | None, plan: PlatformApiPlan | None) -> dict:
    if row is None:
        return {"status": "none", "plan": None}
    return {
        "id": row.id,
        "status": row.status,
        "plan": plan.plan_identifier if plan else None,
        "catalog_version": plan.catalog_version if plan else None,
        "billing_mode": row.billing_mode,
        "billing_interval": row.billing_interval,
        "current_period_start": row.current_period_start.isoformat() if row.current_period_start else None,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "grace_ends_at": row.grace_ends_at.isoformat() if row.grace_ends_at else None,
        "cancel_at_period_end": bool(row.cancel_at_period_end),
    }


@router.get("/pricing")
def public_pricing(db: Session = Depends(get_db)) -> dict:
    _flag("PLATFORM_API_PRICING_ENABLED")
    rows = (
        db.query(PlatformApiPlan)
        .filter(
            PlatformApiPlan.catalog_version == settings.PLATFORM_API_PLAN_CATALOG_VERSION,
            PlatformApiPlan.active.is_(True),
        )
        .order_by(PlatformApiPlan.monthly_price_cents.asc().nullslast())
        .all()
    )
    return {
        "catalog_version": settings.PLATFORM_API_PLAN_CATALOG_VERSION,
        "private_preview": True,
        "plans": [
            {
                "identifier": row.plan_identifier,
                "name": row.display_name,
                "currency": row.currency,
                "monthly_price_cents": row.monthly_price_cents,
                "annual_price_cents": row.annual_price_cents,
                "included_credits": row.included_credits,
                "overage_price_per_1000_cents": row.overage_price_per_1000_cents,
                "overages_allowed": row.overages_allowed,
                "limits": row.limits_json,
                "support_tier": row.support_tier,
                "status": row.status,
            }
            for row in rows
        ],
    }


@router.get("/developer/billing")
def billing_summary(
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    row = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == ctx.organization.id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )
    plan = db.get(PlatformApiPlan, row.plan_id) if row else None
    return {"subscription": _subscription_public(row, plan), "portal_billing_is_separate": True}


@router.post("/developer/sandbox/activate")
def activate_self_service_sandbox(
    request: Request,
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED")
    enrollment = next(
        (
            row
            for row in active_enrollments(db, ctx.organization.id)
            if row.program == "developer_self_service" and "test" in set(row.allowed_environments_json or [])
        ),
        None,
    )
    if enrollment is None:
        raise HTTPException(status_code=403, detail={"code": "self_service_enrollment_required"})
    plan = _active_plan(db, "sandbox")
    existing = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == ctx.organization.id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )
    if existing:
        return {"status": "existing", "subscription": _subscription_public(existing, db.get(PlatformApiPlan, existing.plan_id))}
    row = PlatformApiSubscription(
        organization_id=ctx.organization.id,
        enrollment_id=enrollment.id,
        plan_id=plan.id,
        status="free",
        status_slot="active",
        billing_mode="none",
    )
    db.add(row)
    db.flush()
    record_product_audit(
        db,
        event_type="platform.billing.sandbox_activated",
        subject_type="api_subscription",
        subject_id=row.id,
        organization_id=ctx.organization.id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"catalog_version": plan.catalog_version},
    )
    db.commit()
    return {"status": "activated", "subscription": _subscription_public(row, plan)}


@router.post("/developer/billing/checkout")
def create_api_checkout(
    payload: CheckoutCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    _flag("PLATFORM_API_STRIPE_CHECKOUT_ENABLED")
    if payload.plan not in {"developer", "scale"}:
        raise HTTPException(status_code=422, detail={"code": "checkout_plan_not_supported"})
    canonical_payload = payload.model_dump(mode="json")
    claim, replay = claim_checkout(
        db,
        organization_id=ctx.organization.id,
        client_key=idempotency_key,
        payload=canonical_payload,
        request_id=getattr(request.state, "request_id", None),
    )
    # Persist the local claim before any external Stripe side effect.
    db.commit()
    claim_id = claim.id
    if replay:
        return dict(claim.response_json or {})

    try:
        plan = _active_plan(db, payload.plan)
        price_id = _price_for(plan, payload.billing_interval)
        overage_price_id = _overage_price_for(plan)
        existing = (
            db.query(PlatformApiSubscription)
            .filter(
                PlatformApiSubscription.organization_id == ctx.organization.id,
                PlatformApiSubscription.status_slot == "active",
            )
            .first()
        )
        if existing and existing.status not in {"canceled"}:
            raise HTTPException(status_code=409, detail={"code": "api_subscription_already_exists"})
        _stripe()
        customer_id = ctx.organization.stripe_customer_id
        if not customer_id:
            customer = stripe.Customer.create(
                name=ctx.organization.name,
                metadata={"organization_id": ctx.organization.id, "agroai_customer": "shared"},
                idempotency_key=f"agroai-api-customer-{ctx.organization.id}",
            )
            customer_id = str(customer["id"])
            ctx.organization.stripe_customer_id = customer_id
        if existing is None:
            existing = PlatformApiSubscription(
                organization_id=ctx.organization.id,
                enrollment_id=ctx.platform_enrollment.id,
                plan_id=plan.id,
                status="checkout_pending",
                status_slot="active",
                billing_mode="stripe",
                billing_interval=payload.billing_interval,
                stripe_customer_id=customer_id,
            )
            db.add(existing)
            db.flush()
        else:
            existing.plan_id = plan.id
            existing.status = "checkout_pending"
            existing.billing_interval = payload.billing_interval
            existing.stripe_customer_id = customer_id
        existing.stripe_price_id = price_id
        metadata = {
            "organization_id": ctx.organization.id,
            "api_subscription_id": existing.id,
            "api_plan_id": plan.id,
            "api_plan_identifier": plan.plan_identifier,
            "api_catalog_version": plan.catalog_version,
            "billing_product": "platform_api",
        }
        line_items = [{"price": price_id, "quantity": 1}]
        if overage_price_id:
            # Metered line items do not accept quantity; Stripe derives usage
            # from the configured Billing Meter.
            line_items.append({"price": overage_price_id})
        checkout_kwargs = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": line_items,
            "success_url": f"{settings.APP_URL}/developers/api/billing?checkout=success",
            "cancel_url": f"{settings.APP_URL}/developers/api/billing?checkout=cancelled",
            "client_reference_id": ctx.organization.id,
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "automatic_tax": {"enabled": bool(settings.PLATFORM_API_STRIPE_TAX_ENABLED)},
            "idempotency_key": stripe_checkout_idempotency_key(
                organization_id=ctx.organization.id,
                operation=claim.operation,
                client_key=idempotency_key,
                request_hash=claim.request_hash,
            ),
        }
        if settings.PLATFORM_API_STRIPE_TAX_ENABLED:
            checkout_kwargs["customer_update"] = {"address": "auto"}
        checkout = stripe.checkout.Session.create(
            **checkout_kwargs,
        )
    except HTTPException:
        db.rollback()
        failed_claim = db.get(type(claim), claim_id)
        if failed_claim is not None:
            fail_checkout(failed_claim)
            db.commit()
        raise
    except stripe.error.StripeError as exc:
        db.rollback()
        failed_claim = db.get(type(claim), claim_id)
        if failed_claim is not None:
            fail_checkout(failed_claim)
            db.commit()
        platform_billing_events.labels(event_class="checkout", outcome="failed").inc()
        raise HTTPException(status_code=503, detail={"code": "api_checkout_unavailable", "reason": exc.__class__.__name__}) from exc
    except Exception:
        db.rollback()
        failed_claim = db.get(type(claim), claim_id)
        if failed_claim is not None:
            fail_checkout(failed_claim)
            db.commit()
        raise
    record_product_audit(
        db,
        event_type="platform.billing.checkout_created",
        subject_type="api_subscription",
        subject_id=existing.id,
        organization_id=ctx.organization.id,
        actor_user_id=ctx.user.id,
        request_id=getattr(request.state, "request_id", None),
        metadata={"plan": plan.plan_identifier, "interval": payload.billing_interval},
    )
    response_json = {
        "checkout_url": checkout["url"],
        "subscription": _subscription_public(existing, plan),
    }
    complete_checkout(
        claim,
        subscription_id=existing.id,
        stripe_checkout_session_id=str(checkout.get("id") or "") or None,
        response_json=response_json,
    )
    db.commit()
    platform_billing_events.labels(event_class="checkout", outcome="created").inc()
    return response_json


@router.post("/developer/billing/portal")
def create_api_billing_portal(
    ctx: AuthContext = Depends(require_developer_control_plane),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    row = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == ctx.organization.id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )
    if row is None or not row.stripe_customer_id:
        raise HTTPException(status_code=404, detail={"code": "api_billing_portal_unavailable"})
    _stripe()
    kwargs = {"customer": row.stripe_customer_id, "return_url": f"{settings.APP_URL}/developers/api/billing"}
    if settings.PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION:
        kwargs["configuration"] = settings.PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION
    try:
        session = stripe.billing_portal.Session.create(**kwargs)
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=503, detail={"code": "api_billing_portal_unavailable"}) from exc
    return {"portal_url": session["url"]}


def _event_object(event: dict) -> dict:
    return dict(((event.get("data") or {}).get("object") or {}))


def _platform_event_metadata(obj: dict) -> dict:
    """Read only explicit metadata carried by this billing object."""

    merged = dict(obj.get("metadata") or {})
    for container_name in ("subscription_details", "parent"):
        container = obj.get(container_name)
        if not isinstance(container, dict):
            continue
        details = (
            container.get("subscription_details")
            if container_name == "parent"
            else container
        )
        if isinstance(details, dict):
            for key, value in dict(details.get("metadata") or {}).items():
                merged.setdefault(key, value)
    return merged


def _stripe_subscription_id(obj: dict) -> str | None:
    direct = obj.get("subscription")
    if direct:
        return str(direct)
    if str(obj.get("object") or "") == "subscription" and obj.get("id"):
        return str(obj["id"])
    parent = obj.get("parent")
    if isinstance(parent, dict):
        details = parent.get("subscription_details")
        if isinstance(details, dict) and details.get("subscription"):
            return str(details["subscription"])
    return None


def _subscription_for_event(
    db: Session,
    obj: dict,
    metadata: dict,
) -> PlatformApiSubscription | None:
    local_id = metadata.get("api_subscription_id")
    stripe_subscription_id = _stripe_subscription_id(obj)
    local_row = None
    stripe_row = None
    if local_id:
        local_row = db.get(PlatformApiSubscription, str(local_id))
    if stripe_subscription_id:
        stripe_row = (
            db.query(PlatformApiSubscription)
            .filter(
                PlatformApiSubscription.stripe_subscription_id
                == str(stripe_subscription_id)
            )
            .first()
        )
    if local_row is not None and stripe_row is not None and local_row.id != stripe_row.id:
        return None
    row = local_row or stripe_row
    if row is None:
        return None
    organization_id = metadata.get("organization_id") or obj.get("client_reference_id")
    if organization_id and row.organization_id != str(organization_id):
        return None
    if (
        stripe_subscription_id
        and row.stripe_subscription_id
        and row.stripe_subscription_id != stripe_subscription_id
    ):
        return None
    return row


@router.post("/billing/stripe-webhook")
async def api_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    if not settings.PLATFORM_API_STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail={"code": "api_billing_webhook_not_configured"})
    raw = await request.body()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    try:
        event = stripe.Webhook.construct_event(raw, stripe_signature, settings.PLATFORM_API_STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        platform_billing_events.labels(event_class="stripe_webhook", outcome="signature_denied").inc()
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    event = dict(event)
    if not platform_stripe_livemode_matches(
        mode=settings.PLATFORM_API_STRIPE_MODE,
        livemode=bool(event.get("livemode")),
    ):
        platform_billing_events.labels(
            event_class="stripe_webhook",
            outcome="mode_mismatch",
        ).inc()
        raise HTTPException(
            status_code=503,
            detail={"code": "api_billing_stripe_event_mode_mismatch"},
        )
    event_id = str(event.get("id") or "")
    if not event_id:
        raise HTTPException(status_code=400, detail="Invalid Stripe event")
    existing = db.query(PlatformStripeEvent).filter(PlatformStripeEvent.stripe_event_id == event_id).first()
    if existing:
        platform_billing_events.labels(event_class="stripe_webhook", outcome="duplicate").inc()
        return {"status": "duplicate", "event_id": event_id}
    obj = _event_object(event)
    metadata = _platform_event_metadata(obj)
    billing_product = str(metadata.get("billing_product") or "")
    created = datetime.utcfromtimestamp(int(event.get("created") or 0))
    if billing_product != "platform_api":
        organization_id = metadata.get("organization_id") or obj.get(
            "client_reference_id"
        )
        organization = (
            db.get(Organization, str(organization_id)) if organization_id else None
        )
        row = PlatformStripeEvent(
            stripe_event_id=event_id,
            event_type=str(event.get("type") or "unknown"),
            organization_id=organization.id if organization else None,
            subscription_id=None,
            status="ignored_non_platform_api",
            event_created_at=created,
            payload_digest=hashlib.sha256(raw).hexdigest(),
            safe_metadata_json={
                "livemode": bool(event.get("livemode")),
                "object": str(obj.get("object") or "")[:80],
                "billing_product": billing_product[:80] or None,
            },
            processed_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        platform_billing_events.labels(
            event_class="stripe_webhook",
            outcome="ignored_non_platform_api",
        ).inc()
        return {"status": "ignored_non_platform_api", "event_id": event_id}

    subscription = _subscription_for_event(db, obj, metadata)
    organization = (
        db.get(Organization, subscription.organization_id) if subscription else None
    )
    row = PlatformStripeEvent(
        stripe_event_id=event_id,
        event_type=str(event.get("type") or "unknown"),
        organization_id=organization.id if organization else None,
        subscription_id=subscription.id if subscription else None,
        status="received",
        event_created_at=created,
        payload_digest=hashlib.sha256(raw).hexdigest(),
        safe_metadata_json={
            "livemode": bool(event.get("livemode")),
            "object": str(obj.get("object") or "")[:80],
            "billing_product": "platform_api",
        },
    )
    db.add(row)
    if organization is None or subscription is None:
        row.status = "ignored_non_platform_api"
        row.processed_at = datetime.utcnow()
        db.commit()
        platform_billing_events.labels(
            event_class="stripe_webhook",
            outcome="ignored_non_platform_api",
        ).inc()
        return {"status": "ignored_non_platform_api", "event_id": event_id}
    if subscription.organization_id != organization.id:
        raise HTTPException(status_code=409, detail={"code": "stripe_organization_mapping_conflict"})
    if subscription.stripe_state_updated_at and created < subscription.stripe_state_updated_at:
        row.status = "ignored_out_of_order"
        row.processed_at = datetime.utcnow()
        db.commit()
        platform_billing_events.labels(event_class="stripe_webhook", outcome="out_of_order").inc()
        return {"status": "ignored_out_of_order", "event_id": event_id}
    event_type = row.event_type
    if event_type == "checkout.session.completed":
        subscription.stripe_subscription_id = obj.get("subscription") or subscription.stripe_subscription_id
        subscription.stripe_customer_id = obj.get("customer") or subscription.stripe_customer_id
        subscription.status = "active" if obj.get("payment_status") in {"paid", "no_payment_required"} else "trialing"
    elif event_type.startswith("customer.subscription."):
        subscription.stripe_subscription_id = obj.get("id") or subscription.stripe_subscription_id
        subscription.stripe_customer_id = obj.get("customer") or subscription.stripe_customer_id
        mapped = {
            "trialing": "trialing",
            "active": "active",
            "past_due": "past_due",
            "unpaid": "unpaid",
            "canceled": "canceled",
            "incomplete": "trialing",
            "incomplete_expired": "canceled",
            "paused": "suspended",
        }
        subscription.status = mapped.get(str(obj.get("status")), subscription.status)
        if event_type == "customer.subscription.deleted":
            subscription.status = "canceled"
        subscription.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        if obj.get("current_period_start"):
            subscription.current_period_start = datetime.utcfromtimestamp(int(obj["current_period_start"]))
        if obj.get("current_period_end"):
            subscription.current_period_end = datetime.utcfromtimestamp(int(obj["current_period_end"]))
    elif event_type == "invoice.payment_failed":
        subscription.status = "past_due"
        subscription.grace_ends_at = datetime.utcnow() + timedelta(days=int(settings.PLATFORM_API_BILLING_GRACE_DAYS))
        notify_subscription_state(
            db,
            organization=organization,
            subscription_id=subscription.id,
            notification_type="payment_failed",
            event_id=event_id,
        )
        notify_subscription_state(
            db,
            organization=organization,
            subscription_id=subscription.id,
            notification_type="grace_period_started",
            event_id=event_id,
        )
    elif event_type in {"invoice.paid", "invoice.payment_succeeded"}:
        subscription.status = "active"
        subscription.grace_ends_at = None
    if subscription.status == "canceled":
        notify_subscription_state(
            db,
            organization=organization,
            subscription_id=subscription.id,
            notification_type="subscription_canceled",
            event_id=event_id,
        )
    subscription.stripe_state_updated_at = created
    row.status = "processed"
    row.processed_at = datetime.utcnow()
    record_product_audit(
        db,
        event_type="platform.billing.stripe_event_processed",
        subject_type="api_subscription",
        subject_id=subscription.id,
        organization_id=organization.id,
        actor_type="stripe_webhook",
        metadata={"stripe_event_type": event_type, "subscription_status": subscription.status},
    )
    db.commit()
    platform_billing_events.labels(event_class="stripe_webhook", outcome="processed").inc()
    return {"status": "processed", "event_id": event_id}


@router.post("/admin/billing/meter-outbox/drain")
def drain_meter_outbox(
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_BILLING_ENABLED")
    return publish_pending_meter_outbox(db, limit=100)


@router.post("/admin/billing/meter-outbox/{outbox_id}/retry")
def retry_meter_outbox(
    outbox_id: str,
    payload: AdminBillingAction,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    row = db.get(PlatformStripeMeterOutbox, outbox_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    if row.status not in {"failed", "pending"}:
        raise HTTPException(status_code=409, detail={"code": "meter_outbox_not_retryable"})
    row.status = "pending"
    row.next_attempt_at = datetime.utcnow()
    row.last_error_class = None
    record_product_audit(
        db,
        event_type="platform.billing.meter_retry_requested",
        subject_type="stripe_meter_outbox",
        subject_id=row.id,
        organization_id=row.organization_id,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return {"outbox_id": row.id, "status": row.status}


@router.post("/admin/billing/meter-outbox/backfill")
def backfill_meter_outbox(
    payload: AdminBillingAction,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    created = 0
    reservations = (
        db.query(PlatformCreditReservation)
        .filter(
            PlatformCreditReservation.state == "committed",
            PlatformCreditReservation.overage_credits > 0,
        )
        .order_by(PlatformCreditReservation.created_at.asc())
        .limit(5000)
        .all()
    )
    for reservation in reservations:
        usage = (
            db.query(PlatformApiUsageEvent)
            .filter(
                PlatformApiUsageEvent.organization_id == reservation.organization_id,
                PlatformApiUsageEvent.api_project_id == reservation.api_project_id,
                PlatformApiUsageEvent.idempotency_key == reservation.logical_operation_id,
            )
            .first()
        )
        if usage is None:
            continue
        if db.query(PlatformStripeMeterOutbox).filter_by(usage_event_id=usage.id).first():
            continue
        subscription = (
            db.query(PlatformApiSubscription)
            .filter(
                PlatformApiSubscription.organization_id == reservation.organization_id,
                PlatformApiSubscription.status_slot == "active",
            )
            .first()
        )
        if subscription is None or not subscription.stripe_customer_id:
            continue
        identifier = hashlib.sha256(f"agroai-api-meter:{usage.id}".encode()).hexdigest()
        db.add(
            PlatformStripeMeterOutbox(
                organization_id=reservation.organization_id,
                subscription_id=subscription.id,
                usage_event_id=usage.id,
                meter_event_identifier=identifier,
                meter_event_name=settings.PLATFORM_API_STRIPE_METER_EVENT_NAME or "agroai_api_credits",
                quantity=reservation.overage_credits,
                status="pending",
            )
        )
        created += 1
    record_product_audit(
        db,
        event_type="platform.billing.meter_backfill_completed",
        subject_type="stripe_meter_outbox",
        subject_id="backfill",
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"created": created},
    )
    db.commit()
    return {"created": created}


@router.post("/admin/billing/meter-outbox/reconcile")
def reconcile_meter_outbox(
    payload: AdminBillingAction,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    _stripe()
    if not settings.PLATFORM_API_STRIPE_METER_ID:
        raise HTTPException(status_code=503, detail={"code": "api_billing_meter_not_configured"})
    reconciled = mismatched = skipped = 0
    subscriptions = (
        db.query(PlatformApiSubscription)
        .filter(PlatformApiSubscription.stripe_customer_id.is_not(None))
        .all()
    )
    for subscription in subscriptions:
        if not subscription.current_period_start or not subscription.current_period_end:
            skipped += 1
            continue
        rows = (
            db.query(PlatformStripeMeterOutbox)
            .filter(
                PlatformStripeMeterOutbox.subscription_id == subscription.id,
                PlatformStripeMeterOutbox.status.in_(["exported", "reconciled"]),
                PlatformStripeMeterOutbox.created_at >= subscription.current_period_start,
                PlatformStripeMeterOutbox.created_at < subscription.current_period_end,
            )
            .all()
        )
        expected = sum(int(row.quantity or 0) for row in rows)
        summaries = stripe.billing.Meter.list_event_summaries(
            settings.PLATFORM_API_STRIPE_METER_ID,
            customer=subscription.stripe_customer_id,
            start_time=int(subscription.current_period_start.timestamp()),
            end_time=int(subscription.current_period_end.timestamp()),
            limit=100,
        )
        observed = sum(int(item.get("aggregated_value") or 0) for item in summaries.auto_paging_iter())
        if observed != expected:
            mismatched += 1
            continue
        for row in rows:
            if row.status == "exported":
                row.status = "reconciled"
                row.reconciled_at = datetime.utcnow()
                reconciled += 1
    record_product_audit(
        db,
        event_type="platform.billing.meter_reconciled",
        subject_type="stripe_meter_outbox",
        subject_id="reconciliation",
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"reconciled": reconciled, "mismatched_subscriptions": mismatched, "skipped_subscriptions": skipped},
    )
    db.commit()
    return {"reconciled": reconciled, "mismatched_subscriptions": mismatched, "skipped_subscriptions": skipped}


@router.post("/admin/billing/catalog/activation")
def set_catalog_activation(
    payload: CatalogActivation,
    request: Request,
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _flag("PLATFORM_API_BILLING_ENABLED")
    plans = db.query(PlatformApiPlan).filter(PlatformApiPlan.catalog_version == payload.catalog_version).all()
    costs = db.query(PlatformApiOperationCost).filter(PlatformApiOperationCost.catalog_version == payload.catalog_version).all()
    if not plans or not costs:
        raise HTTPException(status_code=404, detail={"code": "api_catalog_version_not_found"})
    if payload.active and payload.catalog_version != settings.PLATFORM_API_PLAN_CATALOG_VERSION:
        raise HTTPException(status_code=409, detail={"code": "api_catalog_configuration_mismatch"})
    for plan in plans:
        plan.active = payload.active
        plan.status = "private_preview" if payload.active else "commercial_approval_required"
    for cost in costs:
        cost.active = payload.active
    record_product_audit(
        db,
        event_type="platform.billing.catalog_activated" if payload.active else "platform.billing.catalog_deactivated",
        subject_type="api_catalog",
        subject_id=payload.catalog_version,
        actor_user_id=ctx.user.id,
        actor_type="platform_admin",
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"plans": len(plans), "operation_costs": len(costs)},
    )
    db.commit()
    return {"catalog_version": payload.catalog_version, "active": payload.active, "plans": len(plans), "operation_costs": len(costs)}


@router.get("/admin/billing/reconciliation")
def billing_reconciliation(
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    del ctx
    _flag("PLATFORM_API_BILLING_ENABLED")
    return {
        "subscriptions_by_status": {
            status_name: count
            for status_name, count in db.query(PlatformApiSubscription.status, __import__("sqlalchemy").func.count(PlatformApiSubscription.id))
            .group_by(PlatformApiSubscription.status)
            .all()
        },
        "meter_outbox_by_status": {
            status_name: count
            for status_name, count in db.query(PlatformStripeMeterOutbox.status, __import__("sqlalchemy").func.count(PlatformStripeMeterOutbox.id))
            .group_by(PlatformStripeMeterOutbox.status)
            .all()
        },
        "stripe_events_unmapped": db.query(PlatformStripeEvent).filter(PlatformStripeEvent.status == "unmapped").count(),
    }

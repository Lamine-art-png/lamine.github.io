from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib.parse import quote

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_membership
from app.core.config import settings
from app.db.base import get_db
from app.models.saas import BillingEvent, Organization, User, UserPreference
from app.services.commercial_billing_lifecycle import (
    apply_authoritative_billing_event,
    _first_price,
    _commercial_checkout_metadata,
)
from app.services.entitlements import require_owner_or_admin, serialize_entitlements
from app.services.non_customer_access import access_profile_metadata, activate_configured_profile
from app.services.language_registry import canonical_ui_locale
from app.services.product_plans import public_plans, service_add_ons, upgrade_options
from app.services.quota import quota_snapshot

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger("agroai.billing")
WEBHOOK_EVENTS = frozenset({"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted", "invoice.payment_failed", "invoice.paid", "invoice.payment_succeeded"})


class CheckoutRequest(BaseModel):
    organization_id: str
    offer: str | None = None
    plan: str | None = None
    locale: str | None = None


class PortalRequest(BaseModel):
    organization_id: str
    locale: str | None = None


class ReconcileRequest(BaseModel):
    organization_id: str
    session_id: str


_STRIPE_SUPPORTED_LOCALES = {
    "bg", "cs", "da", "de", "el", "en", "en-GB", "es", "es-419", "et", "fi", "fil",
    "fr", "fr-CA", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv", "ms", "mt", "nb",
    "nl", "pl", "pt", "pt-BR", "ro", "ru", "sk", "sl", "sv", "th", "tr", "vi", "zh",
    "zh-HK", "zh-TW",
}


def _customer_locale(db: Session, user: User, requested: str | None = None) -> str:
    value = requested
    if not value:
        preference = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
        value = preference.locale if preference else None
    try:
        canonical = canonical_ui_locale(value or "auto")
    except ValueError:
        canonical = "auto"
    return stripe_checkout_locale(canonical)


# AGRO-AI locale -> Stripe Checkout locale where the codes differ. Every other
# AGRO-AI locale either matches a Stripe code exactly or is not offered by
# Stripe, in which case Checkout uses "auto" (the customer's browser language,
# English when Stripe lacks it). AGRO-AI's own billing UI, emails and stored
# preference always keep the customer's AGRO-AI locale.
_STRIPE_LOCALE_ALIASES = {
    "pt": "pt-BR",
    "fr-FR": "fr",
    "tl": "fil",
    "no": "nb",
    "zh-CN": "zh",
    "es-ES": "es",
    "es-MX": "es-419",
}


def stripe_checkout_locale(agroai_locale: str | None) -> str:
    canonical = (agroai_locale or "auto").strip()
    if canonical == "auto":
        return "auto"
    mapped = _STRIPE_LOCALE_ALIASES.get(canonical, canonical)
    return mapped if mapped in _STRIPE_SUPPORTED_LOCALES else "auto"


def _billing_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "billing_unavailable",
            "message": "Checkout is temporarily unavailable. Please retry or contact AGRO-AI support.",
        },
    )


def _activate_authorized_non_customer_before_billing(db: Session, user: User, org: Organization) -> None:
    """Resolve a verified server-allowlisted identity before any Stripe action.

    This closes the edge case where a founder reaches billing before `/auth/me`
    has performed the normal authenticated-context auto-activation.
    """

    if user.email_verification_status != "verified" or not user.email_verified_at:
        return
    result = activate_configured_profile(db, user=user, org=org)
    if result is None:
        return
    db.commit()
    db.refresh(org)


def _billing_not_required(org: Organization) -> HTTPException | None:
    profile = access_profile_metadata(org)
    if profile["billing_required"]:
        return None
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "billing_not_required",
            "message": "Billing is disabled for this authorized AGRO-AI access profile.",
            "access_profile": profile["profile"],
        },
    )


def _stripe_ready() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise _billing_unavailable()
    if str(getattr(settings, "APP_ENV", "")).lower() in {"production", "prod"} and not settings.STRIPE_SECRET_KEY.startswith(("sk_live_", "rk_live_")):
        raise _billing_unavailable()
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _validate_live_offer(offer: str, config: dict) -> None:
    """Fail closed before charging against a stale, test, or mispriced catalog."""
    if str(getattr(settings, "APP_ENV", "")).lower() not in {"production", "prod"}:
        return
    expected = {
        "professional_monthly": (29900, 1), "professional_annual": (299000, 12),
        "team_monthly": (79900, 1), "team_annual": (799000, 12),
        "network_monthly": (150000, 1), "network_annual": (1500000, 12),
    }.get(offer)
    if not expected:
        return
    if settings.APP_URL.rstrip("/") != "https://app.agroai-pilot.com":
        raise _billing_unavailable()
    try:
        price = stripe.Price.retrieve(config["price"])
    except stripe.error.StripeError:
        raise _billing_unavailable()
    recurring = price.get("recurring") or {}
    if not (price.get("active") and price.get("livemode") and price.get("currency") == "usd"
            and price.get("unit_amount") == expected[0] and recurring.get("interval") == "month"
            and recurring.get("interval_count") == expected[1]):
        logger.error("billing_live_price_mismatch offer=%s", offer)
        raise _billing_unavailable()


def _normalize_offer(payload: CheckoutRequest) -> str:
    raw = (payload.offer or payload.plan or "").strip().lower()
    aliases = {
        "professional": "professional_monthly",
        "pro": "professional_monthly",
        "team": "team_monthly",
        "network": "network_monthly",
        "pilot": "professional_monthly",
        "waterops": "professional_monthly",
        "waterops_monthly": "professional_monthly",
        "assurance": "team_monthly",
        "assurance_monthly": "team_monthly",
        "farm_audit": "assurance_audit_farm",
        "network_audit": "assurance_audit_network",
    }
    return aliases.get(raw, raw)


def _normalize_plan_id(plan: str | None) -> str | None:
    if not plan:
        return None
    return {
        "pilot": "free",
        "pro": "professional",
        "waterops": "professional",
        "assurance": "team",
    }.get(plan, plan)


def _offer_config(offer: str) -> dict:
    offers = {
        "professional_monthly": {
            "price": settings.STRIPE_PRICE_PRO_MONTHLY,
            "mode": "subscription",
            "plan": "professional",
        },
        "professional_annual": {
            "price": settings.STRIPE_PRICE_PRO_ANNUAL,
            "mode": "subscription",
            "plan": "professional",
        },
        "team_monthly": {
            "price": settings.STRIPE_PRICE_TEAM_MONTHLY,
            "mode": "subscription",
            "plan": "team",
        },
        "team_annual": {
            "price": settings.STRIPE_PRICE_TEAM_ANNUAL,
            "mode": "subscription",
            "plan": "team",
        },
        "network_monthly": {
            "price": settings.STRIPE_PRICE_NETWORK_MONTHLY,
            "mode": "subscription",
            "plan": "network",
        },
        "network_annual": {
            "price": settings.STRIPE_PRICE_NETWORK_ANNUAL,
            "mode": "subscription",
            "plan": "network",
        },
        "assurance_audit_farm": {
            "price": settings.STRIPE_PRICE_ASSURANCE_AUDIT_FARM,
            "mode": "payment",
            "plan": None,
        },
        "assurance_audit_network": {
            "price": settings.STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK,
            "mode": "payment",
            "plan": None,
        },
    }
    config = offers.get(offer)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "offer_required",
                "message": "Choose a supported AGRO-AI commercial offer.",
            },
        )
    if not config["price"]:
        raise _billing_unavailable()
    return config


def _create_customer(org: Organization) -> str:
    _stripe_ready()
    try:
        customer = stripe.Customer.create(name=org.name, metadata={"organization_id": org.id}, idempotency_key=f"aep-customer-{org.id}")
    except stripe.error.StripeError:
        raise _billing_unavailable()
    return customer["id"]


@router.get("/plans")
def billing_plans(user: User = Depends(get_current_user)) -> dict:
    current_plan = _normalize_plan_id(user.memberships[0].organization.plan) if user.memberships else "free"
    return {
        "plans": public_plans(),
        "service_add_ons": service_add_ons(),
        "upgrade_options": upgrade_options(current_plan),
        "offers": {
            "professional": {"monthly": "professional_monthly", "annual": "professional_annual"},
            "team": {"monthly": "team_monthly", "annual": "team_annual"},
            "network": {"monthly": "network_monthly", "annual": "network_annual"},
        },
    }


@router.post("/create-checkout-session")
def create_checkout_session(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    offer = _normalize_offer(payload)
    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)
    _activate_authorized_non_customer_before_billing(db, user, org)
    billing_guard = _billing_not_required(org)
    if billing_guard is not None:
        raise billing_guard
    offer_config = _offer_config(offer)
    logger.info("checkout_requested org_id=%s offer=%s", org.id, offer)
    _stripe_ready()
    _validate_live_offer(offer, offer_config)

    # The organization lock serializes first customer creation and checkout
    # retries across tabs and workers. Stripe's matching key covers a timeout
    # after Stripe accepted the request but before this transaction committed.
    org = db.query(Organization).filter_by(id=org.id).populate_existing().with_for_update().one()
    if org.stripe_subscription_id and org.subscription_status in {"active", "trialing"}:
        raise HTTPException(status_code=409, detail={"code": "subscription_already_active"})
    attempt_key = f"aep-checkout:{org.id}:{offer}"
    attempt = db.query(BillingEvent).filter_by(stripe_event_id=attempt_key).with_for_update().first()
    previous = dict(attempt.payload_json or {}) if attempt else {}
    if previous.get("checkout_url") and int(previous.get("expires_at") or 0) > int(datetime.utcnow().timestamp()):
        logger.info("checkout_session_reused org_id=%s offer=%s", org.id, offer)
        return {"checkout_url": previous["checkout_url"], "offer": offer, "mode": offer_config["mode"]}
    sequence = int(previous.get("sequence") or 0) + (1 if previous.get("session_id") else 0)
    customer_id = org.stripe_customer_id or _create_customer(org)
    if not org.stripe_customer_id:
        org.stripe_customer_id = customer_id
        db.flush()

    metadata = _commercial_checkout_metadata(org, offer, offer_config)
    stripe_locale = _customer_locale(db, user, payload.locale)
    metadata["preferred_locale"] = stripe_locale
    _stripe_ready()
    try:
        session_kwargs = {
            "mode": offer_config["mode"],
            "customer": customer_id,
            "line_items": [{"price": offer_config["price"], "quantity": 1}],
            "success_url": f"{settings.APP_URL}/billing?checkout=success&offer={quote(offer)}&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{settings.APP_URL}/billing?checkout=cancelled&offer={quote(offer)}",
            "client_reference_id": org.id,
            "metadata": metadata,
            "locale": stripe_locale,
        }
        if offer_config["mode"] == "subscription":
            session_kwargs["subscription_data"] = {"metadata": metadata}
        else:
            session_kwargs["payment_intent_data"] = {"metadata": metadata}
        session = stripe.checkout.Session.create(**session_kwargs, idempotency_key=f"aep-checkout-{org.id}-{offer}-{sequence}")
    except stripe.error.StripeError:
        logger.warning("checkout_session_failed org_id=%s offer=%s", org.id, offer)
        raise _billing_unavailable()
    if not session.get("url") or not session.get("id"):
        raise _billing_unavailable()
    state = {"session_id": session["id"], "checkout_url": session["url"], "expires_at": int(session.get("expires_at") or datetime.utcnow().timestamp() + 1800), "sequence": sequence}
    if attempt:
        attempt.payload_json = state
    else:
        db.add(BillingEvent(organization_id=org.id, stripe_event_id=attempt_key, event_type="checkout_attempt", payload_json=state))
    db.commit()
    logger.info("checkout_session_created org_id=%s offer=%s", org.id, offer)
    return {"checkout_url": session["url"], "offer": offer, "mode": offer_config["mode"]}


setattr(create_checkout_session, "__agroai_commercial_hardened__", True)


@router.post("/create-portal-session")
def create_portal_session(
    payload: PortalRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)
    _activate_authorized_non_customer_before_billing(db, user, org)
    billing_guard = _billing_not_required(org)
    if billing_guard is not None:
        raise billing_guard
    if not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "billing_portal_unavailable",
                "message": "Billing management is not available for this organization yet.",
            },
        )
    _stripe_ready()
    try:
        session = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=f"{settings.APP_URL}/billing",
            locale=_customer_locale(db, user, payload.locale),
        )
    except stripe.error.StripeError:
        raise _billing_unavailable()
    return {"portal_url": session["url"]}


@router.get("/status")
def billing_status(
    organization_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    org_id = organization_id or (user.memberships[0].organization_id if user.memberships else None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    org, _ = require_org_membership(org_id, user, db)
    _activate_authorized_non_customer_before_billing(db, user, org)
    usage = quota_snapshot(db, org)
    access_profile = access_profile_metadata(org)
    return {
        "plan": _normalize_plan_id(org.plan) or "free",
        "subscription_status": org.subscription_status,
        "current_period_start": org.current_period_start.isoformat() if org.current_period_start else None,
        "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None,
        "cancel_at_period_end": bool(org.cancel_at_period_end),
        "access_profile": access_profile["profile"],
        "billing_required": access_profile["billing_required"],
        "entitlements": serialize_entitlements(org, db),
        "usage": usage,
    }


setattr(billing_status, "__agroai_period_aware__", True)


def _verify_stripe_signature(raw_body: bytes, signature: str | None) -> None:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stripe_webhook_not_configured", "message": "Stripe webhook secret is not configured."},
        )
    if not signature:
        logger.warning("webhook_signature_failed reason=missing")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature")
    try:
        stripe.Webhook.construct_event(raw_body, signature, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        logger.warning("webhook_signature_failed reason=invalid_payload")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe payload")
    except stripe.error.SignatureVerificationError:
        logger.warning("webhook_signature_failed reason=invalid_signature")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")


def _plan_from_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    price_to_plan = {
        settings.STRIPE_PRICE_PRO_MONTHLY: "professional",
        settings.STRIPE_PRICE_PRO_ANNUAL: "professional",
        settings.STRIPE_PRICE_TEAM_MONTHLY: "team",
        settings.STRIPE_PRICE_TEAM_ANNUAL: "team",
        settings.STRIPE_PRICE_NETWORK_MONTHLY: "network",
        settings.STRIPE_PRICE_NETWORK_ANNUAL: "network",
        settings.STRIPE_PRICE_WATEROPS_MONTHLY: "professional",
        settings.STRIPE_PRICE_ASSURANCE_MONTHLY: "team",
        getattr(settings, "STRIPE_PRICE_PRO", ""): "pro",
        getattr(settings, "STRIPE_PRICE_PILOT", ""): "pilot",
        getattr(settings, "STRIPE_PRICE_ENTERPRISE", ""): "enterprise",
        settings.STRIPE_PRICE_ASSURANCE_AUDIT_FARM: "assurance_audit",
        settings.STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK: "assurance_audit",
    }
    return price_to_plan.get(price_id)


def _org_for_event(db: Session, obj: dict) -> Organization | None:
    org_id = (obj.get("metadata") or {}).get("organization_id") or obj.get("client_reference_id")
    customer_id = obj.get("customer")
    subscription_id = obj.get("subscription") or obj.get("id")
    query = db.query(Organization)
    if org_id:
        org = query.filter(Organization.id == org_id).first()
        if org and customer_id and org.stripe_customer_id and org.stripe_customer_id != customer_id:
            logger.warning("billing_webhook_customer_mismatch org_id=%s", org.id)
            return None
        return org
    if customer_id:
        found = query.filter(Organization.stripe_customer_id == customer_id).first()
        if found:
            return found
    if subscription_id:
        return query.filter(Organization.stripe_subscription_id == subscription_id).first()
    return None


def _apply_billing_event(db: Session, org: Organization | None, event_type: str, obj: dict) -> None:
    apply_authoritative_billing_event(db, org, event_type, obj)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    raw = await request.body()
    _verify_stripe_signature(raw, stripe_signature)
    event = json.loads(raw)
    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id or not event_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe event")
    if event_type not in WEBHOOK_EVENTS:
        return {"received": True, "ignored": True}

    obj = ((event.get("data") or {}).get("object") or {})
    org = _org_for_event(db, obj)
    if org:
        org = db.query(Organization).filter_by(id=org.id).populate_existing().with_for_update().one()
    existing = db.query(BillingEvent).filter(BillingEvent.stripe_event_id == event_id).first()
    if existing:
        logger.info("webhook_duplicate_ignored event_id=%s", event_id)
        return {"received": True, "idempotent": True}

    # Stripe can deliver two state changes in the same second or out of order.
    # Read the current subscription in production before mutating access.
    if org and str(getattr(settings, "APP_ENV", "")).lower() in {"production", "prod"}:
        subscription_id = obj.get("id") if event_type.startswith("customer.subscription.") else (
            obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        ) if event_type == "invoice.payment_failed" else None
        if subscription_id:
            _stripe_ready()
            try:
                current = stripe.Subscription.retrieve(subscription_id)
            except stripe.error.StripeError:
                logger.warning("billing_webhook_reconciliation_failed org_id=%s", org.id)
                raise _billing_unavailable()
            if org.stripe_customer_id and current.get("customer") != org.stripe_customer_id:
                raise HTTPException(status_code=400, detail={"code": "subscription_customer_mismatch"})
            if event_type.startswith("customer.subscription."):
                obj = dict(current)
                if event_type == "customer.subscription.deleted" and obj.get("status") != "canceled":
                    event_type = "customer.subscription.updated"
            elif event_type == "invoice.payment_failed" and current.get("status") != "past_due":
                # A later successful payment already recovered the account.
                event_type = "invoice.paid"

    created = int(event.get("created") or 0)
    if org and created:
        ordered_types = {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"} if event_type.startswith("customer.subscription.") else {"invoice.payment_failed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"} if event_type == "invoice.payment_failed" else {event_type}
        recent = db.query(BillingEvent).filter(BillingEvent.organization_id == org.id, BillingEvent.event_type.in_(ordered_types)).all()
        last = max((int((row.payload_json or {}).get("created") or 0) for row in recent), default=0)
        if created < last:
            logger.info("billing_stale_event_ignored org_id=%s event_id=%s", org.id, event_id)
            db.add(BillingEvent(organization_id=org.id, stripe_event_id=event_id, event_type=event_type, payload_json={"created": created, "stale": True}, processed_at=datetime.utcnow()))
            db.commit()
            return {"received": True, "stale": True}
    billing_event = BillingEvent(
        organization_id=org.id if org else None,
        stripe_event_id=event_id,
        event_type=event_type,
        payload_json={"created": created, "object_id": obj.get("id"), "customer": obj.get("customer")},
        processed_at=datetime.utcnow(),
    )
    db.add(billing_event)
    _apply_billing_event(db, org, event_type, obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("webhook_duplicate_ignored event_id=%s", event_id)
        return {"received": True, "idempotent": True}
    logger.info("billing_webhook_applied event_type=%s org_id=%s", event_type, org.id if org else "unresolved")
    if org:
        telemetry = {
            "checkout.session.completed": "checkout_completed_webhook",
            "customer.subscription.created": "subscription_created",
            "customer.subscription.updated": "subscription_updated",
            "customer.subscription.deleted": "subscription_canceled",
            "invoice.payment_failed": "invoice_payment_failed",
        }.get(event_type)
        if telemetry:
            logger.info("%s org_id=%s", telemetry, org.id)
        if event_type.startswith("customer.subscription.") or event_type == "invoice.payment_failed":
            state_event = {"active": "subscription_active", "past_due": "subscription_past_due", "canceled": "subscription_canceled"}.get(org.subscription_status)
            if state_event:
                logger.info("%s org_id=%s", state_event, org.id)
    return {"received": True, "idempotent": False}


@router.post("/reconcile-checkout")
def reconcile_checkout(payload: ReconcileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Read Stripe after redirect; the URL flag itself never grants access."""
    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)
    if not payload.session_id.startswith("cs_") or len(payload.session_id) > 150:
        raise HTTPException(status_code=422, detail={"code": "invalid_checkout_session"})
    _stripe_ready()
    logger.info("billing_reconciliation_started org_id=%s", org.id)
    try:
        session = stripe.checkout.Session.retrieve(payload.session_id)
        metadata = session.get("metadata") or {}
        if metadata.get("organization_id") != org.id or session.get("customer") != org.stripe_customer_id:
            raise HTTPException(status_code=404, detail={"code": "checkout_session_not_found"})
        if session.get("status") == "expired":
            return {"status": "expired"}
        if session.get("status") != "complete" or not session.get("subscription"):
            return {"status": "confirming"}
        subscription = stripe.Subscription.retrieve(session["subscription"])
        if subscription.get("customer") != org.stripe_customer_id:
            raise HTTPException(status_code=404, detail={"code": "checkout_session_not_found"})
        price_id = _first_price(subscription).get("id")
        if not price_id or _plan_from_price(price_id) not in {"professional", "team", "network"}:
            raise _billing_unavailable()
        org = db.query(Organization).filter_by(id=org.id).populate_existing().with_for_update().one()
        if org.stripe_subscription_id and org.stripe_subscription_id != subscription["id"] and org.subscription_status in {"active", "trialing"}:
            raise HTTPException(status_code=409, detail={"code": "subscription_already_active"})
        _apply_billing_event(db, org, "customer.subscription.updated", dict(subscription))
        db.commit()
        if org.subscription_status in {"active", "trialing"}:
            logger.info("billing_reconciliation_succeeded org_id=%s", org.id)
            return {"status": "active", "plan": org.plan}
        return {"status": "confirming"}
    except HTTPException:
        raise
    except stripe.error.StripeError:
        logger.warning("billing_reconciliation_failed org_id=%s", org.id)
        raise _billing_unavailable()

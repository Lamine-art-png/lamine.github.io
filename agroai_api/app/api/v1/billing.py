from __future__ import annotations

import json
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_membership
from app.core.config import settings
from app.db.base import get_db
from app.models.saas import BillingEvent, Organization, UsageEvent, User
from app.services.entitlements import require_owner_or_admin, serialize_entitlements

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    organization_id: str
    # New commercial offer. "plan" kept only for old callers.
    offer: str | None = None
    plan: str | None = None


class PortalRequest(BaseModel):
    organization_id: str


def _stripe_ready() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stripe_not_configured", "message": "Stripe secret key is not configured."},
        )
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _normalize_offer(payload: CheckoutRequest) -> str:
    raw = (payload.offer or payload.plan or "").strip().lower()
    aliases = {
        "pilot": "waterops_monthly",
        "pro": "assurance_monthly",
        "waterops": "waterops_monthly",
        "assurance": "assurance_monthly",
        "farm_audit": "assurance_audit_farm",
        "network_audit": "assurance_audit_network",
    }
    return aliases.get(raw, raw)


def _offer_config(offer: str) -> dict:
    offers = {
        "assurance_audit_farm": {
            "price": settings.STRIPE_PRICE_ASSURANCE_AUDIT_FARM,
            "mode": "payment",
            "plan": "assurance_audit",
        },
        "assurance_audit_network": {
            "price": settings.STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK,
            "mode": "payment",
            "plan": "assurance_audit",
        },
        "waterops_monthly": {
            "price": settings.STRIPE_PRICE_WATEROPS_MONTHLY,
            "mode": "subscription",
            "plan": "waterops",
        },
        "assurance_monthly": {
            "price": settings.STRIPE_PRICE_ASSURANCE_MONTHLY,
            "mode": "subscription",
            "plan": "assurance",
        },
    }
    config = offers.get(offer)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "offer_required",
                "message": "Use assurance_audit_farm, assurance_audit_network, waterops_monthly, or assurance_monthly.",
            },
        )
    if not config["price"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stripe_price_missing", "message": f"Stripe price ID is not configured for {offer}."},
        )
    return config


def _create_customer(org: Organization) -> str:
    _stripe_ready()
    try:
        customer = stripe.Customer.create(name=org.name, metadata={"organization_id": org.id})
    except stripe.error.StripeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "stripe_error", "message": "Stripe customer creation failed."},
        )
    return customer["id"]


@router.post("/create-checkout-session")
def create_checkout_session(payload: CheckoutRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    offer = _normalize_offer(payload)
    offer_config = _offer_config(offer)

    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)

    customer_id = org.stripe_customer_id or _create_customer(org)
    if not org.stripe_customer_id:
        org.stripe_customer_id = customer_id
        db.commit()

    _stripe_ready()
    try:
        session = stripe.checkout.Session.create(
            mode=offer_config["mode"],
            customer=customer_id,
            line_items=[{"price": offer_config["price"], "quantity": 1}],
            success_url=f"{settings.APP_URL}/billing?checkout=success&offer={offer}",
            cancel_url=f"{settings.APP_URL}/billing?checkout=cancelled&offer={offer}",
            client_reference_id=org.id,
            metadata={
                "organization_id": org.id,
                "offer": offer,
                "plan": offer_config["plan"],
                "checkout_mode": offer_config["mode"],
            },
        )
    except stripe.error.StripeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "stripe_error", "message": "Stripe checkout session creation failed."},
        )
    return {"checkout_url": session["url"], "offer": offer, "mode": offer_config["mode"]}


@router.post("/create-portal-session")
def create_portal_session(payload: PortalRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)
    if not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "billing_customer_missing", "message": "No Stripe customer exists for this organization."},
        )
    _stripe_ready()
    try:
        session = stripe.billing_portal.Session.create(customer=org.stripe_customer_id, return_url=f"{settings.APP_URL}/billing")
    except stripe.error.StripeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "stripe_error", "message": "Stripe billing portal session creation failed."},
        )
    return {"portal_url": session["url"]}


@router.get("/status")
def billing_status(organization_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    org_id = organization_id or (user.memberships[0].organization_id if user.memberships else None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    org, _ = require_org_membership(org_id, user, db)
    usage = (
        db.query(UsageEvent.event_type, UsageEvent.quantity)
        .filter(UsageEvent.organization_id == org.id)
        .all()
    )
    totals: dict[str, int] = {}
    for event_type, quantity in usage:
        totals[event_type] = totals.get(event_type, 0) + int(quantity or 0)
    return {
        "plan": org.plan,
        "subscription_status": org.subscription_status,
        "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None,
        "entitlements": serialize_entitlements(org),
        "usage": totals,
    }


def _verify_stripe_signature(raw_body: bytes, signature: str | None) -> None:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stripe_webhook_not_configured", "message": "Stripe webhook secret is not configured."},
        )
    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature")
    try:
        stripe.Webhook.construct_event(raw_body, signature, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")


def _plan_from_price(price_id: str | None) -> str | None:
    if price_id == settings.STRIPE_PRICE_WATEROPS_MONTHLY:
        return "waterops"
    if price_id == settings.STRIPE_PRICE_ASSURANCE_MONTHLY:
        return "assurance"
    if price_id in {settings.STRIPE_PRICE_ASSURANCE_AUDIT_FARM, settings.STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK}:
        return "assurance_audit"
    return None


def _org_for_event(db: Session, obj: dict) -> Organization | None:
    org_id = (obj.get("metadata") or {}).get("organization_id")
    customer_id = obj.get("customer")
    subscription_id = obj.get("subscription") or obj.get("id")
    query = db.query(Organization)
    if org_id:
        return query.filter(Organization.id == org_id).first()
    if customer_id:
        found = query.filter(Organization.stripe_customer_id == customer_id).first()
        if found:
            return found
    if subscription_id:
        return query.filter(Organization.stripe_subscription_id == subscription_id).first()
    return None


def _apply_billing_event(db: Session, org: Organization | None, event_type: str, obj: dict) -> None:
    if not org:
        return
    if event_type == "checkout.session.completed":
        org.stripe_customer_id = obj.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = obj.get("subscription") or org.stripe_subscription_id
        metadata = obj.get("metadata") or {}
        plan = metadata.get("plan")
        checkout_mode = metadata.get("checkout_mode") or obj.get("mode")
        if plan in {"waterops", "assurance"}:
            org.plan = plan
            org.subscription_status = "active"
        elif plan == "assurance_audit" and checkout_mode == "payment":
            org.plan = plan
            org.subscription_status = "paid"
    elif event_type.startswith("customer.subscription."):
        org.stripe_customer_id = obj.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = obj.get("id") or org.stripe_subscription_id
        org.subscription_status = obj.get("status") or org.subscription_status
        items = (((obj.get("items") or {}).get("data") or [{}])[0]).get("price") or {}
        plan = _plan_from_price(items.get("id"))
        if plan:
            org.plan = plan
        if event_type == "customer.subscription.deleted":
            org.plan = "free"
            org.subscription_status = "canceled"
        period_end = obj.get("current_period_end")
        if period_end:
            org.current_period_end = datetime.utcfromtimestamp(int(period_end))
    elif event_type == "invoice.payment_failed":
        org.subscription_status = "past_due"
    elif event_type == "invoice.payment_succeeded" and org.subscription_status in {"past_due", "incomplete"}:
        org.subscription_status = "active"


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
    existing = db.query(BillingEvent).filter(BillingEvent.stripe_event_id == event_id).first()
    if existing:
        return {"received": True, "idempotent": True}
    obj = ((event.get("data") or {}).get("object") or {})
    org = _org_for_event(db, obj)
    billing_event = BillingEvent(
        organization_id=org.id if org else None,
        stripe_event_id=event_id,
        event_type=event_type,
        payload_json=event,
        processed_at=datetime.utcnow(),
    )
    db.add(billing_event)
    _apply_billing_event(db, org, event_type, obj)
    db.commit()
    return {"received": True, "idempotent": False}

"""Authoritative commercial subscription lifecycle and billing runtime hardening.

Stripe Checkout completion is intentionally not treated as proof of an active
subscription. Runtime access follows customer.subscription.* lifecycle events.
One-time services never mutate the SaaS plan.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.saas import Organization


ACTIVE_STATES = {"active", "trialing", "contracted"}
CANONICAL_PLANS = {"free", "professional", "team", "network", "enterprise"}


def _epoch(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    return datetime.utcfromtimestamp(int(value))


def _first_price(obj: dict[str, Any]) -> dict[str, Any]:
    items = (obj.get("items") or {}).get("data") or []
    if not items:
        return {}
    return items[0].get("price") or {}


def apply_authoritative_billing_event(
    db: Any,
    org: Organization | None,
    event_type: str,
    obj: dict[str, Any],
) -> None:
    """Apply only commercially authoritative state transitions."""
    del db  # Kept for compatibility with the billing webhook call signature.
    if org is None:
        return

    if event_type == "checkout.session.completed":
        org.stripe_customer_id = obj.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = obj.get("subscription") or org.stripe_subscription_id
        metadata = obj.get("metadata") or {}
        checkout_mode = metadata.get("checkout_mode") or obj.get("mode")
        if checkout_mode == "subscription":
            org.subscription_source = "stripe"
            if org.subscription_status not in ACTIVE_STATES:
                org.subscription_status = "incomplete"
        return

    if event_type.startswith("customer.subscription."):
        org.stripe_customer_id = obj.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = obj.get("id") or org.stripe_subscription_id
        org.subscription_source = "stripe"

        if event_type == "customer.subscription.deleted":
            org.plan = "free"
            org.subscription_status = "canceled"
            org.current_period_start = None
            org.current_period_end = None
            org.cancel_at_period_end = False
            return

        org.subscription_status = obj.get("status") or org.subscription_status
        metadata_plan = (obj.get("metadata") or {}).get("plan")

        # Import the existing compatibility helpers only at runtime, after the
        # billing module is fully initialized. This preserves legacy price aliases.
        from app.api.v1 import billing as billing_api

        normalized = billing_api._normalize_plan_id(metadata_plan)
        price = _first_price(obj)
        if normalized not in CANONICAL_PLANS:
            normalized = billing_api._normalize_plan_id(billing_api._plan_from_price(price.get("id")))
        if normalized in CANONICAL_PLANS:
            org.plan = normalized

        org.stripe_price_id = price.get("id") or org.stripe_price_id
        org.stripe_product_id = price.get("product") or org.stripe_product_id
        org.current_period_start = _epoch(obj.get("current_period_start")) or org.current_period_start
        org.current_period_end = _epoch(obj.get("current_period_end")) or org.current_period_end
        org.cancel_at_period_end = bool(obj.get("cancel_at_period_end", False))
        return

    if event_type == "invoice.payment_failed":
        org.subscription_status = "past_due"
        return

    # invoice.payment_succeeded, invoice.paid, and payment_intent.succeeded are
    # non-authoritative for SaaS activation. They must not independently unlock
    # runtime access or mutate the paid plan.


def _commercial_checkout_metadata(org: Organization, offer: str, offer_config: dict[str, Any]) -> dict[str, str]:
    mode = str(offer_config["mode"])
    period = "one_time" if mode != "subscription" else ("annual" if offer.endswith("_annual") else "monthly")
    metadata = {
        "organization_id": str(org.id),
        "offer": str(offer),
        "checkout_mode": mode,
        "billing_period": period,
        "plan_version": str(getattr(org, "plan_version", None) or "2026-07"),
    }
    plan = offer_config.get("plan")
    if plan:
        metadata["plan"] = str(plan)
    return metadata


def _hardened_create_checkout_session(payload, user=None, db=None):
    """Replacement body for the already-registered FastAPI checkout endpoint."""
    offer = _normalize_offer(payload)
    org, membership = require_org_membership(payload.organization_id, user, db)
    require_owner_or_admin(membership.role)
    offer_config = _offer_config(offer)

    customer_id = org.stripe_customer_id or _create_customer(org)
    if not org.stripe_customer_id:
        org.stripe_customer_id = customer_id
        db.commit()

    metadata = _commercial_checkout_metadata(org, offer, offer_config)
    _stripe_ready()
    try:
        session_kwargs = {
            "mode": offer_config["mode"],
            "customer": customer_id,
            "line_items": [{"price": offer_config["price"], "quantity": 1}],
            "success_url": f"{settings.APP_URL}/billing?checkout=success&offer={offer}",
            "cancel_url": f"{settings.APP_URL}/billing?checkout=cancelled&offer={offer}",
            "client_reference_id": org.id,
            "metadata": metadata,
        }
        if offer_config["mode"] == "subscription":
            session_kwargs["subscription_data"] = {"metadata": metadata}
        else:
            session_kwargs["payment_intent_data"] = {"metadata": metadata}
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "stripe_error", "message": "Stripe checkout session creation failed."},
        )
    return {"checkout_url": session["url"], "offer": offer, "mode": offer_config["mode"]}


def _period_aware_billing_status(organization_id=None, user=None, db=None):
    """Replacement body for the already-registered FastAPI billing status endpoint."""
    org_id = organization_id or (user.memberships[0].organization_id if user.memberships else None)
    if not org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="organization_id is required")
    org, _ = require_org_membership(org_id, user, db)
    usage = quota_snapshot(db, org)
    return {
        "plan": _normalize_plan_id(org.plan) or "free",
        "subscription_status": org.subscription_status,
        "current_period_start": org.current_period_start.isoformat() if org.current_period_start else None,
        "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None,
        "cancel_at_period_end": bool(org.cancel_at_period_end),
        "entitlements": serialize_entitlements(org, db),
        "usage": usage,
    }


def install_commercial_billing_lifecycle() -> None:
    """Install the complete commercial subscription boundary at application startup."""
    from app.api.v1 import billing as billing_api
    from app.services.commercial_subscription_restrictions import install_inactive_subscription_restrictions
    from app.services.quota import quota_snapshot

    # Subscription state restrictions are part of the same runtime boundary: a
    # selected paid plan with inactive billing must behave like Free for access.
    install_inactive_subscription_restrictions()
    billing_api._apply_billing_event = apply_authoritative_billing_event

    original_offer_config = billing_api._offer_config
    if not getattr(original_offer_config, "__agroai_commercial_hardened__", False):
        def hardened_offer_config(offer: str) -> dict:
            config = dict(original_offer_config(offer))
            if config.get("mode") == "payment":
                config["plan"] = None
            return config

        setattr(hardened_offer_config, "__agroai_commercial_hardened__", True)
        billing_api._offer_config = hardened_offer_config

    # Patch registered endpoint function objects in place. FastAPI already holds
    # references to these objects, so preserving identity keeps the dependency
    # graph intact while replacing only runtime behavior.
    billing_api._commercial_checkout_metadata = _commercial_checkout_metadata
    billing_api.quota_snapshot = quota_snapshot

    checkout_endpoint = billing_api.create_checkout_session
    if not getattr(checkout_endpoint, "__agroai_commercial_hardened__", False):
        checkout_endpoint.__code__ = _hardened_create_checkout_session.__code__
        setattr(checkout_endpoint, "__agroai_commercial_hardened__", True)

    status_endpoint = billing_api.billing_status
    if not getattr(status_endpoint, "__agroai_period_aware__", False):
        status_endpoint.__code__ = _period_aware_billing_status.__code__
        setattr(status_endpoint, "__agroai_period_aware__", True)

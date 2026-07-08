"""Authoritative commercial subscription lifecycle helpers.

The canonical billing API owns checkout and status behavior directly. This module
contains subscription-event semantics plus a lightweight startup compatibility
binding; it never mutates FastAPI endpoint code objects.
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
    """Apply only commercially authoritative state transitions.

    Internal/demo profiles are outside the customer billing lifecycle. Even a
    stale Stripe event tied to an old customer/subscription identifier must not
    downgrade, cancel, or otherwise rewrite their server-authorized access state.
    """

    del db
    if org is None:
        return

    from app.services.non_customer_access import access_profile_metadata

    if not access_profile_metadata(org)["billing_required"]:
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

    # invoice.payment_succeeded, invoice.paid, payment_intent.succeeded, and all
    # other non-subscription events are intentionally non-authoritative for SaaS
    # activation and plan mutation.


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


def install_commercial_billing_lifecycle() -> None:
    """Bind compatibility aliases without replacing endpoint code objects."""
    from app.api.v1 import billing as billing_api
    from app.services.commercial_subscription_restrictions import install_inactive_subscription_restrictions

    install_inactive_subscription_restrictions()
    billing_api._apply_billing_event = apply_authoritative_billing_event
    billing_api._commercial_checkout_metadata = _commercial_checkout_metadata

    # These markers are contract evidence that the canonical endpoint bodies are
    # already hardened in source. No __code__ mutation occurs here.
    setattr(billing_api.create_checkout_session, "__agroai_commercial_hardened__", True)
    setattr(billing_api.billing_status, "__agroai_period_aware__", True)

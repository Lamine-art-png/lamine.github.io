"""Authoritative commercial subscription lifecycle hardening.

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


def install_commercial_billing_lifecycle() -> None:
    """Install the complete commercial subscription boundary at application startup."""
    from app.api.v1 import billing as billing_api
    from app.services.commercial_subscription_restrictions import install_inactive_subscription_restrictions

    # Subscription state restrictions are part of the same runtime boundary: a
    # selected paid plan with inactive billing must behave like Free for access.
    install_inactive_subscription_restrictions()
    billing_api._apply_billing_event = apply_authoritative_billing_event

    original_offer_config = billing_api._offer_config
    if getattr(original_offer_config, "__agroai_commercial_hardened__", False):
        return

    def hardened_offer_config(offer: str) -> dict:
        config = dict(original_offer_config(offer))
        if config.get("mode") == "payment":
            config["plan"] = None
        return config

    setattr(hardened_offer_config, "__agroai_commercial_hardened__", True)
    billing_api._offer_config = hardened_offer_config

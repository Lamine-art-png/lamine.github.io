"""Subscription-state restrictions applied after plan, contract, and overrides."""
from __future__ import annotations

from typing import Any

from app.services import commercial_control


_ORIGINAL_RESOLVER = commercial_control.resolve_effective_entitlements


def resolve_with_subscription_restrictions(db: Any, org: Any, *, at_time=None):
    """Downgrade inactive paid plans to Free-equivalent runtime access.

    The selected paid plan remains visible for billing/recovery UX, but runtime
    capabilities and quotas cannot leak through an incomplete, past-due, canceled,
    or otherwise inactive subscription.
    """
    effective = _ORIGINAL_RESOLVER(db, org, at_time=at_time)
    if effective.plan == "free" or effective.subscription_status in commercial_control.ACTIVE_PAID_STATES:
        return effective

    free_values = commercial_control.BASE_ENTITLEMENTS["free"]
    values = dict(effective.values)
    sources = dict(effective.sources)
    restriction_source = f"subscription:{effective.subscription_status or 'inactive'}"

    for key in list(values):
        if key.startswith("quota."):
            values[key] = free_values.get(key)
        elif key == "intelligence.profile":
            values[key] = free_values["intelligence.profile"]
        else:
            values[key] = free_values.get(key, "locked")
        sources[key] = restriction_source

    return commercial_control.EffectiveEntitlements(
        organization_id=effective.organization_id,
        plan=effective.plan,
        plan_version=effective.plan_version,
        customer_class=effective.customer_class,
        organization_type=effective.organization_type,
        subscription_status=effective.subscription_status,
        values=values,
        sources=sources,
    )


def install_inactive_subscription_restrictions() -> None:
    """Install once into the canonical commercial-control module."""
    current = commercial_control.resolve_effective_entitlements
    if getattr(current, "__agroai_inactive_subscription_hardened__", False):
        return
    setattr(resolve_with_subscription_restrictions, "__agroai_inactive_subscription_hardened__", True)
    commercial_control.resolve_effective_entitlements = resolve_with_subscription_restrictions

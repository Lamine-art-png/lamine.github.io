"""Server-authoritative launch state for live Platform API billing.

The founder approved the `2026-07-provisional` Developer and Scale commercial
catalog and migration 028 activated it in production. That approval is part of
the release contract, not a browser or stale environment toggle. Production
therefore treats the billing, pricing, Checkout, meter-export, and quota flags
as enabled whenever the approved live Stripe catalog is selected.

Non-production environments retain the ordinary feature flags.
"""
from __future__ import annotations

from typing import Any


APPROVED_LIVE_CATALOG = "2026-07-provisional"
LIVE_BILLING_CAPABILITIES = frozenset(
    {
        "PLATFORM_API_BILLING_ENABLED",
        "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
        "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
        "PLATFORM_API_PRICING_ENABLED",
        "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
    }
)


def live_billing_release_approved(config: Any) -> bool:
    environment = str(getattr(config, "APP_ENV", "development") or "development").strip().lower()
    catalog = str(
        getattr(config, "PLATFORM_API_PLAN_CATALOG_VERSION", "") or ""
    ).strip()
    operation_catalog = str(
        getattr(config, "PLATFORM_API_OPERATION_COST_CATALOG_VERSION", "") or ""
    ).strip()
    stripe_mode = str(getattr(config, "PLATFORM_API_STRIPE_MODE", "") or "").strip().lower()
    return bool(
        environment in {"production", "prod"}
        and catalog == APPROVED_LIVE_CATALOG
        and operation_catalog == APPROVED_LIVE_CATALOG
        and stripe_mode == "live"
    )


def billing_capability_enabled(config: Any, name: str) -> bool:
    """Return the effective capability state without trusting stale toggles."""

    if name in LIVE_BILLING_CAPABILITIES and live_billing_release_approved(config):
        return True
    return bool(getattr(config, name, False))


def effective_billing_capabilities(config: Any) -> dict[str, bool]:
    return {
        name: billing_capability_enabled(config, name)
        for name in sorted(LIVE_BILLING_CAPABILITIES)
    }

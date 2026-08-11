"""Earliest-process production launch contract for Platform API billing.

Python imports ``sitecustomize`` automatically during interpreter startup unless
it is launched with ``-S``. Render starts Uvicorn with normal Python startup, so
this hook runs before ``app.core.config`` constructs its immutable settings
snapshot, regardless of whether Render invokes ``start-production.sh`` or calls
Uvicorn directly.

The founder-approved live Developer and Scale catalog is enabled only when the
complete live Stripe wiring is present. Partial, test-mode, or malformed
configuration remains disabled and therefore fails closed.
"""
from __future__ import annotations

import os


_APPROVED_CATALOG = "2026-07-provisional"
_REQUIRED_IDENTIFIERS = {
    "PLATFORM_API_STRIPE_SECRET_KEY": "sk_live_",
    "PLATFORM_API_STRIPE_WEBHOOK_SECRET": "whsec_",
    "PLATFORM_API_STRIPE_METER_ID": "mtr_",
    "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_OVERAGE_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_OVERAGE_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_SCALE_MONTHLY_OVERAGE_PRICE_ID": "price_",
    "PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID": "price_",
}
_LIVE_CAPABILITIES = (
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
)


def _complete_live_configuration() -> bool:
    if os.getenv("PLATFORM_API_STRIPE_MODE", "").strip().lower() != "live":
        return False
    if os.getenv("PLATFORM_API_PLAN_CATALOG_VERSION", _APPROVED_CATALOG).strip() != _APPROVED_CATALOG:
        return False
    if os.getenv("PLATFORM_API_OPERATION_COST_CATALOG_VERSION", _APPROVED_CATALOG).strip() != _APPROVED_CATALOG:
        return False
    if os.getenv("PLATFORM_API_STRIPE_METER_EVENT_NAME", "").strip() != "agroai_api_credits":
        return False
    return all(
        os.getenv(name, "").strip().startswith(prefix)
        for name, prefix in _REQUIRED_IDENTIFIERS.items()
    )


if _complete_live_configuration():
    for capability in _LIVE_CAPABILITIES:
        os.environ[capability] = "true"
    os.environ["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] = "true"

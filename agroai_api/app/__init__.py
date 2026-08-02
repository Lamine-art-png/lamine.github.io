"""AGRO-AI API application package."""
from __future__ import annotations

import os
from typing import Literal


# This package is imported before ``app.main`` and therefore before
# ``app.core.config`` constructs the immutable Settings snapshot. Render may
# start Uvicorn through its console entry point, which does not reliably import
# a project-local ``sitecustomize.py``. Keep the approved live billing launch
# contract here so every valid ``app.main:app`` start path sees the same state.
#
# The override is deliberately fail-closed: it activates only when the complete
# live Stripe configuration is present, including all interval-specific Prices.
_APPROVED_PLATFORM_API_CATALOG = "2026-07-provisional"
_LIVE_BILLING_IDENTIFIERS = {
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
_LIVE_BILLING_CAPABILITIES = (
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
)


def _complete_live_platform_billing_configuration() -> bool:
    if os.getenv("PLATFORM_API_STRIPE_MODE", "").strip().lower() != "live":
        return False
    if (
        os.getenv(
            "PLATFORM_API_PLAN_CATALOG_VERSION",
            _APPROVED_PLATFORM_API_CATALOG,
        ).strip()
        != _APPROVED_PLATFORM_API_CATALOG
    ):
        return False
    if (
        os.getenv(
            "PLATFORM_API_OPERATION_COST_CATALOG_VERSION",
            _APPROVED_PLATFORM_API_CATALOG,
        ).strip()
        != _APPROVED_PLATFORM_API_CATALOG
    ):
        return False
    if (
        os.getenv("PLATFORM_API_STRIPE_METER_EVENT_NAME", "").strip()
        != "agroai_api_credits"
    ):
        return False
    return all(
        os.getenv(name, "").strip().startswith(prefix)
        for name, prefix in _LIVE_BILLING_IDENTIFIERS.items()
    )


if _complete_live_platform_billing_configuration():
    for _capability in _LIVE_BILLING_CAPABILITIES:
        os.environ[_capability] = "true"
    os.environ["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] = "true"


from pydantic import BaseModel, Field  # noqa: E402

__version__ = "1.1.0"


class TeamInvitationCreateRequest(BaseModel):
    """Request body for creating a team invitation.

    FastAPI resolves some postponed route annotations during router
    registration. This package module is imported before app.main, so exposing
    the request model here keeps legacy product-shell annotations resolvable at
    startup.
    """

    email: str = Field(min_length=3, max_length=240)
    role: Literal["owner", "admin", "manager", "operator", "viewer"] = "viewer"


__import__("builtins").TeamInvitationCreateRequest = TeamInvitationCreateRequest

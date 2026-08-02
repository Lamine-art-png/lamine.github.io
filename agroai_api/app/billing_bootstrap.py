"""Non-secret runtime contract for the live Platform API billing launch.

The module is imported before the immutable application Settings object is
constructed. It may inspect environment variable *names and identifier shapes*,
but it never exposes secret values. Complete live wiring enables the founder-
approved Developer and Scale billing capabilities. Partial wiring remains
closed and can be diagnosed through a safe production status payload.
"""
from __future__ import annotations

import os
from typing import Mapping, MutableMapping


APPROVED_CATALOG = "2026-07-provisional"
PLATFORM_STRIPE_SECRET = "PLATFORM_API_STRIPE_SECRET_KEY"
SHARED_STRIPE_SECRET = "STRIPE_SECRET_KEY"
LIVE_CAPABILITIES = (
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
)
REQUIRED_IDENTIFIERS: Mapping[str, str] = {
    PLATFORM_STRIPE_SECRET: "sk_live_",
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


def _text(values: Mapping[str, str], name: str) -> str:
    return str(values.get(name, "") or "").strip()


def _resolved_platform_stripe_secret(values: Mapping[str, str]) -> tuple[str, str]:
    """Resolve a live server key without ever returning it in diagnostics.

    AGRO-AI already has one server-side Stripe integration for the Enterprise
    Portal. Platform API billing can safely share that account credential when
    the dedicated Platform variable is absent, but only when the shared key is
    explicitly a live secret key. Test keys and malformed values never cross
    this boundary.
    """

    dedicated = _text(values, PLATFORM_STRIPE_SECRET)
    if dedicated:
        return dedicated, "dedicated"
    shared = _text(values, SHARED_STRIPE_SECRET)
    if shared.startswith("sk_live_"):
        return shared, "shared_live_server_key"
    return "", "missing"


def _adopt_shared_live_stripe_secret(values: MutableMapping[str, str]) -> bool:
    dedicated = _text(values, PLATFORM_STRIPE_SECRET)
    if dedicated:
        return False
    shared = _text(values, SHARED_STRIPE_SECRET)
    if not shared.startswith("sk_live_"):
        return False
    values[PLATFORM_STRIPE_SECRET] = shared
    return True


def diagnose_live_billing_environment(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    missing: list[str] = []
    invalid: list[str] = []

    stripe_mode = _text(values, "PLATFORM_API_STRIPE_MODE").lower()
    if not stripe_mode:
        missing.append("PLATFORM_API_STRIPE_MODE")
    elif stripe_mode != "live":
        invalid.append("PLATFORM_API_STRIPE_MODE")

    catalog = str(
        values.get("PLATFORM_API_PLAN_CATALOG_VERSION", APPROVED_CATALOG)
        or APPROVED_CATALOG
    ).strip()
    if catalog != APPROVED_CATALOG:
        invalid.append("PLATFORM_API_PLAN_CATALOG_VERSION")

    operation_catalog = str(
        values.get("PLATFORM_API_OPERATION_COST_CATALOG_VERSION", APPROVED_CATALOG)
        or APPROVED_CATALOG
    ).strip()
    if operation_catalog != APPROVED_CATALOG:
        invalid.append("PLATFORM_API_OPERATION_COST_CATALOG_VERSION")

    # The backend's canonical event name is stable and safe to default. Requiring
    # a duplicate Render value here previously made an otherwise complete live
    # deployment fail closed for a non-secret constant.
    meter_event_name = str(
        values.get("PLATFORM_API_STRIPE_METER_EVENT_NAME", "agroai_api_credits")
        or "agroai_api_credits"
    ).strip()
    if meter_event_name != "agroai_api_credits":
        invalid.append("PLATFORM_API_STRIPE_METER_EVENT_NAME")

    secret_value, secret_source = _resolved_platform_stripe_secret(values)
    for name, prefix in REQUIRED_IDENTIFIERS.items():
        raw = secret_value if name == PLATFORM_STRIPE_SECRET else _text(values, name)
        if not raw:
            missing.append(name)
        elif not raw.startswith(prefix):
            invalid.append(name)

    missing = sorted(set(missing))
    invalid = sorted(set(invalid))
    complete = not missing and not invalid
    return {
        "complete_live_configuration": complete,
        "missing": missing,
        "invalid": invalid,
        "stripe_mode": stripe_mode or "missing",
        "stripe_secret_source": secret_source,
        "catalog_version": catalog,
        "operation_cost_catalog_version": operation_catalog,
        "meter_event_name_valid": meter_event_name == "agroai_api_credits",
    }


def apply_live_billing_bootstrap(environment: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    inherited = _adopt_shared_live_stripe_secret(values)
    diagnosis = diagnose_live_billing_environment(values)
    diagnosis["shared_live_secret_inherited"] = inherited
    if bool(diagnosis["complete_live_configuration"]):
        for capability in LIVE_CAPABILITIES:
            values[capability] = "true"
        values["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] = "true"
    else:
        values.pop("PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED", None)
    return diagnosis


def safe_runtime_billing_status(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    diagnosis = diagnose_live_billing_environment(values)
    flags = {
        capability: _text(values, capability).lower() == "true"
        for capability in LIVE_CAPABILITIES
    }
    bootstrapped = _text(values, "PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED").lower() == "true"
    return {
        "status": "ready" if bool(diagnosis["complete_live_configuration"]) and bootstrapped and all(flags.values()) else "not_ready",
        "bootstrapped": bootstrapped,
        "complete_live_configuration": diagnosis["complete_live_configuration"],
        "missing": diagnosis["missing"],
        "invalid": diagnosis["invalid"],
        "stripe_mode": diagnosis["stripe_mode"],
        "stripe_secret_source": diagnosis["stripe_secret_source"],
        "catalog_version": diagnosis["catalog_version"],
        "operation_cost_catalog_version": diagnosis["operation_cost_catalog_version"],
        "meter_event_name_valid": diagnosis["meter_event_name_valid"],
        "effective_flags": flags,
    }

"""Non-secret runtime contract for the live Platform API billing launch.

The module is imported before the immutable application Settings object is
constructed. It may inspect environment variable *names and identifier shapes*,
but it never exposes secret values. Complete live wiring enables the founder-
approved Developer and Scale billing capabilities. Partial wiring remains
closed and can be diagnosed through a safe production status payload.
"""
from __future__ import annotations

import os
from typing import Mapping


APPROVED_CATALOG = "2026-07-provisional"
LIVE_CAPABILITIES = (
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
)
REQUIRED_IDENTIFIERS: Mapping[str, str] = {
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


def diagnose_live_billing_environment(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    missing: list[str] = []
    invalid: list[str] = []

    stripe_mode = str(values.get("PLATFORM_API_STRIPE_MODE", "") or "").strip().lower()
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

    for name, prefix in REQUIRED_IDENTIFIERS.items():
        raw = str(values.get(name, "") or "").strip()
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
        "catalog_version": catalog,
        "operation_cost_catalog_version": operation_catalog,
        "meter_event_name_valid": meter_event_name == "agroai_api_credits",
    }


def apply_live_billing_bootstrap(environment: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    diagnosis = diagnose_live_billing_environment(values)
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
        capability: str(values.get(capability, "") or "").strip().lower() == "true"
        for capability in LIVE_CAPABILITIES
    }
    bootstrapped = str(
        values.get("PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED", "") or ""
    ).strip().lower() == "true"
    return {
        "status": "ready" if bool(diagnosis["complete_live_configuration"]) and bootstrapped and all(flags.values()) else "not_ready",
        "bootstrapped": bootstrapped,
        "complete_live_configuration": diagnosis["complete_live_configuration"],
        "missing": diagnosis["missing"],
        "invalid": diagnosis["invalid"],
        "stripe_mode": diagnosis["stripe_mode"],
        "catalog_version": diagnosis["catalog_version"],
        "operation_cost_catalog_version": diagnosis["operation_cost_catalog_version"],
        "meter_event_name_valid": diagnosis["meter_event_name_valid"],
        "effective_flags": flags,
    }

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = (
    "PLATFORM_API_BILLING_ENABLED",
    "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
    "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
    "PLATFORM_API_PRICING_ENABLED",
    "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
)
ENVIRONMENT_KEYS = (
    *CAPABILITIES,
    "PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED",
    "PLATFORM_API_STRIPE_MODE",
    "PLATFORM_API_PLAN_CATALOG_VERSION",
    "PLATFORM_API_OPERATION_COST_CATALOG_VERSION",
    "PLATFORM_API_STRIPE_SECRET_KEY",
    "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
    "PLATFORM_API_STRIPE_METER_ID",
    "PLATFORM_API_STRIPE_METER_EVENT_NAME",
    "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID",
    "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID",
    "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_OVERAGE_PRICE_ID",
    "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_OVERAGE_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_MONTHLY_OVERAGE_PRICE_ID",
    "PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID",
)


def _live_environment() -> dict[str, str]:
    return {
        "PLATFORM_API_STRIPE_MODE": "live",
        "PLATFORM_API_PLAN_CATALOG_VERSION": "2026-07-provisional",
        "PLATFORM_API_OPERATION_COST_CATALOG_VERSION": "2026-07-provisional",
        "PLATFORM_API_STRIPE_SECRET_KEY": "sk_live_contract",
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET": "whsec_contract",
        "PLATFORM_API_STRIPE_METER_ID": "mtr_contract",
        "PLATFORM_API_STRIPE_METER_EVENT_NAME": "agroai_api_credits",
        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID": "price_dev_month",
        "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID": "price_dev_year",
        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_OVERAGE_PRICE_ID": "price_dev_over_month",
        "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_OVERAGE_PRICE_ID": "price_dev_over_year",
        "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID": "price_scale_month",
        "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID": "price_scale_year",
        "PLATFORM_API_STRIPE_SCALE_MONTHLY_OVERAGE_PRICE_ID": "price_scale_over_month",
        "PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID": "price_scale_over_year",
    }


def _import_application_package(extra: dict[str, str]) -> dict[str, str | None]:
    env = os.environ.copy()
    for name in ENVIRONMENT_KEYS:
        env.pop(name, None)
    env.update(extra)
    code = (
        "import app, json, os; "
        f"names={CAPABILITIES!r}; "
        "print(json.dumps({name: os.getenv(name) for name in (*names, 'PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED')}))"
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_application_package_bootstraps_complete_live_billing_without_sitecustomize():
    result = _import_application_package(_live_environment())
    assert result["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] == "true"
    assert all(result[name] == "true" for name in CAPABILITIES)


def test_application_package_refuses_test_mode():
    values = _live_environment()
    values["PLATFORM_API_STRIPE_MODE"] = "test"
    result = _import_application_package(values)
    assert result["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] is None
    assert all(result[name] is None for name in CAPABILITIES)


def test_application_package_refuses_partial_live_configuration():
    values = _live_environment()
    values.pop("PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID")
    result = _import_application_package(values)
    assert result["PLATFORM_API_LIVE_BILLING_BOOTSTRAPPED"] is None
    assert all(result[name] is None for name in CAPABILITIES)

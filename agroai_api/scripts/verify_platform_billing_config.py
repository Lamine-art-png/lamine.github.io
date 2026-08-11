#!/usr/bin/env python3
"""Fail-closed production preflight for Platform API Stripe billing.

This script is run during Render startup after database migrations and before
Uvicorn accepts traffic. It never creates or changes Stripe resources. When
live Platform API billing is enabled, it verifies the configured live account,
all fixed and metered Prices, the Billing Meter, the webhook endpoint, and an
active Customer Portal configuration. Any mismatch stops the deployment.
"""
from __future__ import annotations

import sys
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import stripe

from app.core.config import settings


WEBHOOK_URL = "https://api.agroai-pilot.com/v1/platform/billing/stripe-webhook"
REQUIRED_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
}

PRICE_CONTRACTS = {
    "developer_monthly": {
        "setting": "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID",
        "interval": "month",
        "usage_type": "licensed",
        "unit_amount": 14900,
    },
    "developer_annual": {
        "setting": "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID",
        "interval": "year",
        "usage_type": "licensed",
        "unit_amount": 143000,
    },
    "developer_overage_monthly": {
        "setting": "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_OVERAGE_PRICE_ID",
        "interval": "month",
        "usage_type": "metered",
        "package_amount": 75,
        "package_size": 1000,
    },
    "developer_overage_annual": {
        "setting": "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_OVERAGE_PRICE_ID",
        "interval": "year",
        "usage_type": "metered",
        "package_amount": 75,
        "package_size": 1000,
    },
    "scale_monthly": {
        "setting": "PLATFORM_API_STRIPE_SCALE_MONTHLY_PRICE_ID",
        "interval": "month",
        "usage_type": "licensed",
        "unit_amount": 74900,
    },
    "scale_annual": {
        "setting": "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID",
        "interval": "year",
        "usage_type": "licensed",
        "unit_amount": 719000,
    },
    "scale_overage_monthly": {
        "setting": "PLATFORM_API_STRIPE_SCALE_MONTHLY_OVERAGE_PRICE_ID",
        "interval": "month",
        "usage_type": "metered",
        "package_amount": 35,
        "package_size": 1000,
    },
    "scale_overage_annual": {
        "setting": "PLATFORM_API_STRIPE_SCALE_ANNUAL_OVERAGE_PRICE_ID",
        "interval": "year",
        "usage_type": "metered",
        "package_amount": 35,
        "package_size": 1000,
    },
}


class BillingPreflightError(RuntimeError):
    pass


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _required_setting(name: str, prefix: str | None = None) -> str:
    value = str(getattr(settings, name, "") or "").strip()
    if not value:
        raise BillingPreflightError(f"{name} is missing")
    if prefix and not value.startswith(prefix):
        raise BillingPreflightError(f"{name} has the wrong identifier type")
    return value


def _retry(label: str, fn: Callable[[], Any], attempts: int = 3) -> Any:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise BillingPreflightError(f"Stripe check failed for {label}: {type(last).__name__}") from last


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _validate_price(name: str, price: Any, contract: dict[str, Any], meter_id: str) -> None:
    if not bool(_value(price, "active")):
        raise BillingPreflightError(f"{name} Price is inactive")
    if not bool(_value(price, "livemode")):
        raise BillingPreflightError(f"{name} Price is not live")
    if str(_value(price, "currency") or "").lower() != "usd":
        raise BillingPreflightError(f"{name} Price currency is not USD")
    if str(_value(price, "type") or "") != "recurring":
        raise BillingPreflightError(f"{name} Price is not recurring")

    recurring = _value(price, "recurring") or {}
    if str(_value(recurring, "interval") or "") != contract["interval"]:
        raise BillingPreflightError(f"{name} Price has the wrong billing interval")
    if str(_value(recurring, "usage_type") or "") != contract["usage_type"]:
        raise BillingPreflightError(f"{name} Price has the wrong usage type")

    if contract["usage_type"] == "licensed":
        if int(_value(price, "unit_amount") or 0) != contract["unit_amount"]:
            raise BillingPreflightError(f"{name} Price amount does not match the approved catalog")
        return

    configured_meter = str(_value(recurring, "meter") or "")
    if configured_meter != meter_id:
        raise BillingPreflightError(f"{name} Price is not attached to the configured meter")

    package_amount = contract["package_amount"]
    package_size = contract["package_size"]
    unit_amount = _value(price, "unit_amount")
    unit_amount_decimal = _decimal(_value(price, "unit_amount_decimal"))
    transform = _value(price, "transform_quantity") or {}
    divide_by = int(_value(transform, "divide_by") or 0)

    package_pricing_ok = int(unit_amount or 0) == package_amount and divide_by == package_size
    expected_decimal_per_raw_unit = Decimal(package_amount) / Decimal(package_size)
    decimal_pricing_ok = (
        not transform
        and unit_amount_decimal is not None
        and unit_amount_decimal == expected_decimal_per_raw_unit
    )
    if not (package_pricing_ok or decimal_pricing_ok):
        raise BillingPreflightError(f"{name} overage amount/package size is incorrect")


def _validate_meter(meter: Any) -> None:
    if not bool(_value(meter, "livemode")):
        raise BillingPreflightError("Billing Meter is not live")
    if str(_value(meter, "status") or "") != "active":
        raise BillingPreflightError("Billing Meter is not active")
    if str(_value(meter, "event_name") or "") != "agroai_api_credits":
        raise BillingPreflightError("Billing Meter event name is incorrect")

    aggregation = _value(meter, "default_aggregation") or {}
    if str(_value(aggregation, "formula") or "") != "sum":
        raise BillingPreflightError("Billing Meter aggregation is not sum")
    customer_mapping = _value(meter, "customer_mapping") or {}
    if str(_value(customer_mapping, "event_payload_key") or "") != "stripe_customer_id":
        raise BillingPreflightError("Billing Meter customer payload key is incorrect")
    value_settings = _value(meter, "value_settings") or {}
    if str(_value(value_settings, "event_payload_key") or "") != "value":
        raise BillingPreflightError("Billing Meter value payload key is incorrect")


def _validate_webhook() -> None:
    endpoints = _retry("webhook endpoints", lambda: stripe.WebhookEndpoint.list(limit=100))
    matching = [
        endpoint
        for endpoint in (_value(endpoints, "data") or [])
        if str(_value(endpoint, "url") or "").rstrip("/") == WEBHOOK_URL
        and bool(_value(endpoint, "livemode"))
        and str(_value(endpoint, "status") or "") == "enabled"
    ]
    if not matching:
        raise BillingPreflightError("Enabled live Platform API webhook endpoint was not found")
    enabled = set(_value(matching[0], "enabled_events") or [])
    if "*" not in enabled and not REQUIRED_WEBHOOK_EVENTS.issubset(enabled):
        missing = sorted(REQUIRED_WEBHOOK_EVENTS - enabled)
        raise BillingPreflightError(f"Platform API webhook is missing required events: {','.join(missing)}")


def _validate_customer_portal() -> None:
    configurations = _retry(
        "Customer Portal configurations",
        lambda: stripe.billing_portal.Configuration.list(limit=100),
    )
    active = [row for row in (_value(configurations, "data") or []) if bool(_value(row, "active"))]
    if not active:
        raise BillingPreflightError("No active Stripe Customer Portal configuration exists")

    for config in active:
        features = _value(config, "features") or {}
        payment = _value(features, "payment_method_update") or {}
        invoices = _value(features, "invoice_history") or {}
        cancel = _value(features, "subscription_cancel") or {}
        customer_update = _value(features, "customer_update") or {}
        if (
            bool(_value(payment, "enabled"))
            and bool(_value(invoices, "enabled"))
            and bool(_value(cancel, "enabled"))
            and bool(_value(customer_update, "enabled"))
        ):
            return
    raise BillingPreflightError(
        "Customer Portal is active but payment methods, invoices, billing details, and cancellation are not all enabled"
    )


def run() -> None:
    if not bool(getattr(settings, "PLATFORM_API_BILLING_ENABLED", False)):
        print("Platform API billing preflight: skipped (billing disabled)")
        return

    required_flags = (
        "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
        "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
        "PLATFORM_API_PRICING_ENABLED",
        "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED",
    )
    disabled = [name for name in required_flags if not bool(getattr(settings, name, False))]
    if disabled:
        raise BillingPreflightError(f"Live billing flags are incomplete: {','.join(disabled)}")

    mode = str(getattr(settings, "PLATFORM_API_STRIPE_MODE", "") or "").strip().lower()
    if mode != "live":
        raise BillingPreflightError("PLATFORM_API_STRIPE_MODE must be live")

    secret = _required_setting("PLATFORM_API_STRIPE_SECRET_KEY", "sk_live_")
    _required_setting("PLATFORM_API_STRIPE_WEBHOOK_SECRET", "whsec_")
    meter_id = _required_setting("PLATFORM_API_STRIPE_METER_ID", "mtr_")
    event_name = _required_setting("PLATFORM_API_STRIPE_METER_EVENT_NAME")
    if event_name != "agroai_api_credits":
        raise BillingPreflightError("PLATFORM_API_STRIPE_METER_EVENT_NAME is incorrect")

    stripe.api_key = secret
    account = _retry("account authentication", stripe.Account.retrieve)
    if not bool(_value(account, "charges_enabled")):
        raise BillingPreflightError("Stripe account is not enabled for charges")

    meter = _retry("Billing Meter", lambda: stripe.billing.Meter.retrieve(meter_id))
    _validate_meter(meter)

    for name, contract in PRICE_CONTRACTS.items():
        price_id = _required_setting(contract["setting"], "price_")
        price = _retry(name, lambda price_id=price_id: stripe.Price.retrieve(price_id))
        _validate_price(name, price, contract, meter_id)

    _validate_webhook()
    _validate_customer_portal()
    print("Platform API billing preflight: GREEN (live account, 8 Prices, meter, webhook, portal)")


def main() -> int:
    try:
        run()
    except BillingPreflightError as exc:
        print(f"FATAL Platform API billing preflight: {exc}", file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Non-executable Stripe resource helpers for AGRO-AI Platform API billing.

This module contains no activation entrypoint. Commercial mutation is available only
through the monthly activator and its protected workflow.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import stripe


CATALOG_VERSION = "2026-07-provisional"
METER_EVENT_NAME = "agroai_api_credits"
WEBHOOK_URL = "https://api.agroai-pilot.com/v1/platform/billing/stripe-webhook"
PORTAL_RETURN_URL = "https://platform.agroai-pilot.com/billing"

WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "checkout.session.expired",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
]


@dataclass(frozen=True)
class Plan:
    identifier: str
    display_name: str
    monthly_cents: int
    included_credits: int
    overage_cents_per_1000: int
    support_tier: str
    limits: dict[str, Any]

    @property
    def product_name(self) -> str:
        return f"AGRO-AI Platform API — {self.display_name}"

    @property
    def description(self) -> str:
        return (
            f"{self.display_name} access to the AGRO-AI Platform API with "
            f"{self.included_credits:,} included API credits each month, "
            f"server-side credentials, metered usage, and {self.support_tier} support."
        )


PLANS = [
    Plan(
        identifier="developer",
        display_name="Developer",
        monthly_cents=14_900,
        included_credits=250_000,
        overage_cents_per_1000=75,
        support_tier="email",
        limits={
            "projects": 3,
            "live_projects": 1,
            "service_accounts": 5,
            "keys": 5,
            "webhooks": 3,
            "request_log_retention_days": 30,
        },
    ),
    Plan(
        identifier="scale",
        display_name="Scale",
        monthly_cents=74_900,
        included_credits=2_000_000,
        overage_cents_per_1000=35,
        support_tier="priority",
        limits={
            "projects": 10,
            "live_projects": 5,
            "service_accounts": 20,
            "keys": 20,
            "webhooks": 20,
            "request_log_retention_days": 90,
        },
    ),
]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except Exception:
        return {}


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _items(page: Any) -> list[Any]:
    return list(_value(page, "data", []) or [])


def _metadata(value: Any) -> dict[str, str]:
    raw = _dict(_value(value, "metadata", {}))
    return {str(key): str(item) for key, item in raw.items()}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _mode_from_key(secret_key: str) -> str | None:
    if secret_key.startswith("sk_test_"):
        return "test"
    if secret_key.startswith("sk_live_"):
        return "live"
    return None


def assert_secret_mode(secret_key: str, mode: str) -> None:
    observed = _mode_from_key(secret_key)
    if observed != mode:
        raise RuntimeError(
            f"Stripe key mode mismatch: selected={mode}, "
            f"observed={observed or 'unknown'}"
        )


def catalog_metadata(**extra: str) -> dict[str, str]:
    return {
        "agroai_product": "platform_api",
        "catalog_version": CATALOG_VERSION,
        **extra,
    }


def _matches_metadata(value: Any, expected: dict[str, str]) -> bool:
    actual = _metadata(value)
    return all(actual.get(key) == str(item) for key, item in expected.items())


def _list_products() -> list[Any]:
    return _items(stripe.Product.list(active=True, limit=100))


def create_or_reuse_product(plan: Plan, apply: bool) -> tuple[str | None, str]:
    if not apply:
        return None, "planned"
    expected = catalog_metadata(plan_identifier=plan.identifier)
    existing = next(
        (item for item in _list_products() if _matches_metadata(item, expected)),
        None,
    )
    if existing is not None:
        return str(_value(existing, "id")), "reused"
    created = stripe.Product.create(
        name=plan.product_name,
        description=plan.description,
        metadata=expected,
    )
    return str(_value(created, "id")), "created"


def _list_meters() -> list[Any]:
    return _items(stripe.billing.Meter.list(limit=100))


def _validate_meter(meter: Any) -> None:
    aggregation = _dict(_value(meter, "default_aggregation", {}))
    mapping = _dict(_value(meter, "customer_mapping", {}))
    value_settings = _dict(_value(meter, "value_settings", {}))
    if aggregation.get("formula") != "sum":
        raise RuntimeError("Existing Stripe meter must aggregate with formula=sum")
    if mapping.get("type") != "by_id":
        raise RuntimeError("Existing Stripe meter customer mapping must be by_id")
    if mapping.get("event_payload_key") != "stripe_customer_id":
        raise RuntimeError("Existing Stripe meter customer key must be stripe_customer_id")
    if value_settings.get("event_payload_key") != "value":
        raise RuntimeError("Existing Stripe meter value key must be value")


def create_or_reuse_meter(apply: bool) -> tuple[str | None, str]:
    if not apply:
        return None, "planned"
    existing = next(
        (
            item
            for item in _list_meters()
            if str(_value(item, "event_name", "")) == METER_EVENT_NAME
        ),
        None,
    )
    if existing is not None:
        _validate_meter(existing)
        return str(_value(existing, "id")), "reused"
    created = stripe.billing.Meter.create(
        display_name="AGRO-AI Platform API credits",
        event_name=METER_EVENT_NAME,
        default_aggregation={"formula": "sum"},
        customer_mapping={
            "type": "by_id",
            "event_payload_key": "stripe_customer_id",
        },
        value_settings={"event_payload_key": "value"},
    )
    return str(_value(created, "id")), "created"


def _list_prices(product_id: str) -> list[Any]:
    return _items(stripe.Price.list(product=product_id, active=True, limit=100))


def _recurring(value: Any) -> dict[str, Any]:
    return _dict(_value(value, "recurring", {}))


def _price_matches(
    value: Any,
    *,
    amount_cents: int | None,
    amount_decimal_cents: str | None,
    interval: str,
    usage_type: str,
    meter_id: str | None,
    metadata: dict[str, str],
) -> bool:
    if not _matches_metadata(value, metadata):
        return False
    recurring = _recurring(value)
    if recurring.get("interval") != interval:
        return False
    if recurring.get("usage_type") != usage_type:
        return False
    observed_meter = recurring.get("meter")
    if isinstance(observed_meter, dict):
        observed_meter = observed_meter.get("id")
    if meter_id and str(observed_meter or "") != meter_id:
        return False
    if amount_cents is not None:
        if int(_value(value, "unit_amount", -1) or -1) != amount_cents:
            return False
    if amount_decimal_cents is not None:
        observed = str(_value(value, "unit_amount_decimal", "") or "")
        try:
            if float(observed) != float(amount_decimal_cents):
                return False
        except (TypeError, ValueError):
            return False
    return True


def create_or_reuse_price(
    *,
    plan: Plan,
    product_id: str | None,
    component: str,
    interval: str,
    amount_cents: int | None,
    amount_decimal_cents: str | None,
    usage_type: str,
    meter_id: str | None,
    apply: bool,
) -> tuple[str | None, str]:
    metadata = catalog_metadata(
        plan_identifier=plan.identifier,
        billing_component=component,
    )
    if product_id:
        for existing in _list_prices(product_id):
            if _price_matches(
                existing,
                amount_cents=amount_cents,
                amount_decimal_cents=amount_decimal_cents,
                interval=interval,
                usage_type=usage_type,
                meter_id=meter_id,
                metadata=metadata,
            ):
                return str(_value(existing, "id")), "reused"
            if _matches_metadata(existing, metadata):
                raise RuntimeError(
                    f"Existing price for {plan.identifier}/{component} does not "
                    "match the approved immutable catalog."
                )
    if not apply:
        return None, "planned"
    if not product_id:
        raise RuntimeError("Product ID missing while applying price creation")
    recurring: dict[str, Any] = {
        "interval": interval,
        "usage_type": usage_type,
    }
    if meter_id:
        recurring["meter"] = meter_id
    kwargs: dict[str, Any] = {
        "currency": "usd",
        "product": product_id,
        "recurring": recurring,
        "metadata": metadata,
        "nickname": f"{plan.display_name} {component.replace('_', ' ')}",
        "lookup_key": (
            f"agroai_platform_{plan.identifier}_{component}_"
            f"{_slug(CATALOG_VERSION)}"
        ),
    }
    if amount_cents is not None:
        kwargs["unit_amount"] = amount_cents
    else:
        kwargs["unit_amount_decimal"] = amount_decimal_cents
    created = stripe.Price.create(**kwargs)
    return str(_value(created, "id")), "created"


def create_or_reuse_portal_configuration(apply: bool) -> tuple[str | None, str]:
    if not apply:
        return None, "planned"
    expected = catalog_metadata(configuration="platform_api")
    existing = next(
        (
            item
            for item in _items(stripe.billing_portal.Configuration.list(limit=100))
            if bool(_value(item, "active", False))
            and _matches_metadata(item, expected)
        ),
        None,
    )
    if existing is not None:
        return str(_value(existing, "id")), "reused"
    created = stripe.billing_portal.Configuration.create(
        name="AGRO-AI Platform API billing",
        default_return_url=PORTAL_RETURN_URL,
        business_profile={
            "headline": "Manage your AGRO-AI Platform API subscription.",
            "privacy_policy_url": "https://agroai-pilot.com/privacy-policy",
            "terms_of_service_url": "https://agroai-pilot.com/terms-of-service",
        },
        features={
            "customer_update": {
                "enabled": True,
                "allowed_updates": ["address", "email", "name", "phone", "tax_id"],
            },
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {
                "enabled": True,
                "mode": "at_period_end",
                "cancellation_reason": {
                    "enabled": True,
                    "options": [
                        "too_expensive",
                        "missing_features",
                        "switched_service",
                        "unused",
                        "other",
                    ],
                },
            },
            "subscription_update": {"enabled": False},
        },
        metadata=expected,
    )
    return str(_value(created, "id")), "created"


def _validate_webhook(endpoint: Any) -> None:
    enabled = set(_value(endpoint, "enabled_events", []) or [])
    missing = sorted(set(WEBHOOK_EVENTS) - enabled)
    if missing:
        raise RuntimeError(f"Existing Stripe webhook is missing events: {missing}")
    if str(_value(endpoint, "status", "")) != "enabled":
        raise RuntimeError("Existing Stripe webhook endpoint is disabled")


def create_or_reuse_webhook(
    url: str,
    apply: bool,
    *,
    api_version: str,
) -> tuple[str | None, str | None, str]:
    if not apply:
        return None, None, "planned"
    expected = catalog_metadata(webhook="platform_api")
    same_url = [
        item
        for item in _items(stripe.WebhookEndpoint.list(limit=100))
        if str(_value(item, "url", "")) == url
    ]
    existing = next(
        (item for item in same_url if _matches_metadata(item, expected)),
        None,
    )
    if existing is not None:
        _validate_webhook(existing)
        observed_version = str(_value(existing, "api_version", "") or "")
        if observed_version and observed_version != api_version:
            raise RuntimeError(
                f"Existing Stripe webhook API version is {observed_version}, "
                f"expected {api_version}"
            )
        return str(_value(existing, "id")), None, "reused"
    if same_url:
        raise RuntimeError(
            "A Stripe webhook already exists at the Platform API URL but is not "
            "owned by the Platform API billing catalog."
        )
    created = stripe.WebhookEndpoint.create(
        url=url,
        enabled_events=WEBHOOK_EVENTS,
        description="AGRO-AI Platform API subscription and invoice lifecycle",
        metadata=expected,
        api_version=api_version,
    )
    secret = str(_value(created, "secret", "") or "")
    if not secret.startswith("whsec_"):
        raise RuntimeError("Stripe did not return a webhook signing secret")
    return str(_value(created, "id")), secret, "created"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def write_secrets(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def digest_public_report(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

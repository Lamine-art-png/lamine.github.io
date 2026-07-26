"""Provision AGRO-AI Platform API Stripe resources safely and idempotently.

This command never changes application feature flags or database catalog state. It creates
(or reuses) Stripe products, recurring prices, a billing meter, metered overage prices,
a customer-portal configuration, and the dedicated Platform API webhook endpoint.

Live mode is deliberately fail-closed:
- the key prefix must match the selected mode;
- --apply is required;
- the exact confirmation phrase is required;
- --approve-current-catalog is required because the repository catalog is still named
  ``2026-07-provisional``.

Secrets are written only to ``--secrets-output`` with mode 0600. They are never included
in the public JSON report or printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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

CONFIRMATIONS = {
    "test": "PROVISION AGROAI PLATFORM TEST BILLING",
    "live": "PROVISION AGROAI PLATFORM LIVE BILLING",
}


@dataclass(frozen=True)
class Plan:
    identifier: str
    display_name: str
    monthly_cents: int
    annual_cents: int
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
            f"{self.included_credits:,} included API credits per billing period, "
            f"server-side credentials, metered usage, and {self.support_tier} support."
        )


PLANS = [
    Plan(
        identifier="developer",
        display_name="Developer",
        monthly_cents=14900,
        annual_cents=143000,
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
        monthly_cents=74900,
        annual_cents=719000,
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
    data = _value(page, "data", [])
    return list(data or [])


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


def _assert_secret_mode(secret_key: str, mode: str) -> None:
    observed = _mode_from_key(secret_key)
    if observed != mode:
        raise RuntimeError(
            f"Stripe key mode mismatch: selected={mode}, observed={observed or 'unknown'}"
        )


def _confirmation(args: argparse.Namespace) -> None:
    if not args.apply:
        return
    required = CONFIRMATIONS[args.mode]
    if args.confirmation != required:
        raise RuntimeError(
            f"Refusing to mutate Stripe. Exact confirmation required: {required}"
        )
    if not args.approve_current_catalog:
        raise RuntimeError(
            "Refusing to provision the current pricing catalog without "
            "--approve-current-catalog."
        )


def _catalog_metadata(**extra: str) -> dict[str, str]:
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


def _find_product(plan: Plan) -> Any | None:
    expected = _catalog_metadata(plan_identifier=plan.identifier)
    return next(
        (
            item
            for item in _list_products()
            if _matches_metadata(item, expected)
        ),
        None,
    )


def _create_or_reuse_product(plan: Plan, apply: bool) -> tuple[str | None, str]:
    if not apply:
        return None, "planned"
    existing = _find_product(plan)
    if existing is not None:
        return str(_value(existing, "id")), "reused"
    created = stripe.Product.create(
        name=plan.product_name,
        description=plan.description,
        metadata=_catalog_metadata(plan_identifier=plan.identifier),
    )
    return str(_value(created, "id")), "created"


def _list_meters() -> list[Any]:
    return _items(stripe.billing.Meter.list(limit=100))


def _find_meter() -> Any | None:
    return next(
        (
            item
            for item in _list_meters()
            if str(_value(item, "event_name", "")) == METER_EVENT_NAME
        ),
        None,
    )


def _validate_meter(meter: Any) -> None:
    aggregation = _dict(_value(meter, "default_aggregation", {}))
    mapping = _dict(_value(meter, "customer_mapping", {}))
    value_settings = _dict(_value(meter, "value_settings", {}))
    if aggregation.get("formula") != "sum":
        raise RuntimeError("Existing Stripe meter does not aggregate with formula=sum")
    if mapping.get("type") != "by_id":
        raise RuntimeError("Existing Stripe meter customer mapping must be by_id")
    if mapping.get("event_payload_key") != "stripe_customer_id":
        raise RuntimeError(
            "Existing Stripe meter customer key must be stripe_customer_id"
        )
    if value_settings.get("event_payload_key") != "value":
        raise RuntimeError("Existing Stripe meter value key must be value")


def _create_or_reuse_meter(apply: bool) -> tuple[str | None, str]:
    existing = _find_meter()
    if existing is not None:
        _validate_meter(existing)
        return str(_value(existing, "id")), "reused"
    if not apply:
        return None, "planned"
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


def _price_metadata(plan: Plan, component: str) -> dict[str, str]:
    return _catalog_metadata(
        plan_identifier=plan.identifier,
        billing_component=component,
    )


def _list_prices(product_id: str) -> list[Any]:
    return _items(
        stripe.Price.list(
            product=product_id,
            active=True,
            limit=100,
        )
    )


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
    if meter_id and str(recurring.get("meter") or "") != meter_id:
        return False
    if amount_cents is not None and int(_value(value, "unit_amount", -1) or -1) != amount_cents:
        return False
    if amount_decimal_cents is not None:
        observed = str(_value(value, "unit_amount_decimal", "") or "")
        try:
            if float(observed) != float(amount_decimal_cents):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _create_or_reuse_price(
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
    metadata = _price_metadata(plan, component)
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
                    f"Existing price for {plan.identifier}/{component} does not match "
                    "the approved catalog. Create a new catalog version instead of "
                    "mutating an immutable Stripe Price."
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


def _list_portal_configurations() -> list[Any]:
    return _items(stripe.billing_portal.Configuration.list(limit=100))


def _find_portal_configuration() -> Any | None:
    expected = _catalog_metadata(configuration="platform_api")
    return next(
        (
            item
            for item in _list_portal_configurations()
            if bool(_value(item, "active", False))
            and _matches_metadata(item, expected)
        ),
        None,
    )


def _create_or_reuse_portal_configuration(apply: bool) -> tuple[str | None, str]:
    if not apply:
        return None, "planned"
    existing = _find_portal_configuration()
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
        metadata=_catalog_metadata(configuration="platform_api"),
    )
    return str(_value(created, "id")), "created"


def _list_webhook_endpoints() -> list[Any]:
    return _items(stripe.WebhookEndpoint.list(limit=100))


def _find_webhook_endpoint(url: str) -> Any | None:
    expected = _catalog_metadata(webhook="platform_api")
    candidates = [
        item
        for item in _list_webhook_endpoints()
        if str(_value(item, "url", "")) == url
    ]
    for candidate in candidates:
        if _matches_metadata(candidate, expected):
            return candidate
    if candidates:
        raise RuntimeError(
            "A Stripe webhook endpoint already exists at the Platform API URL but "
            "is not owned by the Platform API billing catalog."
        )
    return None


def _validate_webhook(endpoint: Any) -> None:
    enabled = set(_value(endpoint, "enabled_events", []) or [])
    missing = sorted(set(WEBHOOK_EVENTS) - enabled)
    if missing:
        raise RuntimeError(
            f"Existing Stripe webhook endpoint is missing events: {missing}"
        )
    if str(_value(endpoint, "status", "")) != "enabled":
        raise RuntimeError("Existing Stripe webhook endpoint is disabled")


def _create_or_reuse_webhook(
    url: str,
    apply: bool,
) -> tuple[str | None, str | None, str]:
    if not apply:
        return None, None, "planned"
    existing = _find_webhook_endpoint(url)
    if existing is not None:
        _validate_webhook(existing)
        return str(_value(existing, "id")), None, "reused"
    created = stripe.WebhookEndpoint.create(
        url=url,
        enabled_events=WEBHOOK_EVENTS,
        description="AGRO-AI Platform API subscription and invoice lifecycle",
        metadata=_catalog_metadata(webhook="platform_api"),
    )
    secret = str(_value(created, "secret", "") or "")
    if not secret.startswith("whsec_"):
        raise RuntimeError("Stripe did not return a webhook signing secret")
    return str(_value(created, "id")), secret, "created"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _env_lines(values: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in sorted(values.items()))


def _write_secrets(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_env_lines(values))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision AGRO-AI Platform API Stripe resources."
    )
    parser.add_argument("--mode", choices=("test", "live"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--approve-current-catalog", action="store_true")
    parser.add_argument("--webhook-url", default=WEBHOOK_URL)
    parser.add_argument(
        "--public-output",
        default="platform-api-stripe-provisioning.json",
    )
    parser.add_argument(
        "--secrets-output",
        default="platform-api-stripe-secrets.env",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    _confirmation(args)

    secret_key = (os.environ.get("PLATFORM_API_STRIPE_SECRET_KEY") or "").strip()
    if args.apply:
        if not secret_key:
            raise RuntimeError("PLATFORM_API_STRIPE_SECRET_KEY is required with --apply")
        _assert_secret_mode(secret_key, args.mode)
        stripe.api_key = secret_key

    report: dict[str, Any] = {
        "contract": "agroai-platform-api-stripe-provisioning-v1",
        "mode": args.mode,
        "applied": bool(args.apply),
        "catalog_version": CATALOG_VERSION,
        "meter_event_name": METER_EVENT_NAME,
        "webhook_url": args.webhook_url,
        "resources": {},
        "render_env": {},
    }

    if args.apply:
        meter_id, meter_action = _create_or_reuse_meter(True)
    else:
        meter_id, meter_action = None, "planned"
    report["resources"]["meter"] = {"id": meter_id, "action": meter_action}

    render_env: dict[str, str] = {
        "PLATFORM_API_STRIPE_MODE": args.mode,
        "PLATFORM_API_STRIPE_METER_EVENT_NAME": METER_EVENT_NAME,
    }
    if meter_id:
        render_env["PLATFORM_API_STRIPE_METER_ID"] = meter_id

    for plan in PLANS:
        product_id, product_action = _create_or_reuse_product(plan, args.apply)
        monthly_id, monthly_action = _create_or_reuse_price(
            plan=plan,
            product_id=product_id,
            component="monthly",
            interval="month",
            amount_cents=plan.monthly_cents,
            amount_decimal_cents=None,
            usage_type="licensed",
            meter_id=None,
            apply=args.apply,
        )
        annual_id, annual_action = _create_or_reuse_price(
            plan=plan,
            product_id=product_id,
            component="annual",
            interval="year",
            amount_cents=plan.annual_cents,
            amount_decimal_cents=None,
            usage_type="licensed",
            meter_id=None,
            apply=args.apply,
        )
        overage_decimal = f"{plan.overage_cents_per_1000 / 1000:.12f}".rstrip("0").rstrip(".")
        overage_id, overage_action = _create_or_reuse_price(
            plan=plan,
            product_id=product_id,
            component="overage",
            interval="month",
            amount_cents=None,
            amount_decimal_cents=overage_decimal,
            usage_type="metered",
            meter_id=meter_id,
            apply=args.apply,
        )
        report["resources"][plan.identifier] = {
            "product": {"id": product_id, "action": product_action},
            "monthly_price": {"id": monthly_id, "action": monthly_action},
            "annual_price": {"id": annual_id, "action": annual_action},
            "overage_price": {
                "id": overage_id,
                "action": overage_action,
                "unit_amount_decimal_cents_per_credit": overage_decimal,
            },
            "included_credits": plan.included_credits,
            "limits": plan.limits,
        }
        prefix = plan.identifier.upper()
        if monthly_id:
            render_env[f"PLATFORM_API_STRIPE_{prefix}_MONTHLY_PRICE_ID"] = monthly_id
        if annual_id:
            render_env[f"PLATFORM_API_STRIPE_{prefix}_ANNUAL_PRICE_ID"] = annual_id
        if overage_id:
            render_env[f"PLATFORM_API_STRIPE_{prefix}_OVERAGE_PRICE_ID"] = overage_id

    portal_id, portal_action = _create_or_reuse_portal_configuration(args.apply)
    report["resources"]["customer_portal"] = {
        "id": portal_id,
        "action": portal_action,
    }
    if portal_id:
        render_env["PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION"] = portal_id

    webhook_id, webhook_secret, webhook_action = _create_or_reuse_webhook(
        args.webhook_url,
        args.apply,
    )
    report["resources"]["webhook"] = {
        "id": webhook_id,
        "action": webhook_action,
        "secret_returned": bool(webhook_secret),
    }

    feature_flags = {
        "PLATFORM_API_BILLING_ENABLED": "true",
        "PLATFORM_API_STRIPE_CHECKOUT_ENABLED": "true",
        "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED": "true",
        "PLATFORM_API_PRICING_ENABLED": "true",
        "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED": "true",
    }
    render_env.update(feature_flags)
    report["render_env"] = dict(sorted(render_env.items()))

    public_path = Path(args.public_output)
    _write_json(public_path, report)

    secret_values: dict[str, str] = {}
    if secret_key:
        secret_values["PLATFORM_API_STRIPE_SECRET_KEY"] = secret_key
    if webhook_secret:
        secret_values["PLATFORM_API_STRIPE_WEBHOOK_SECRET"] = webhook_secret
    if secret_values:
        _write_secrets(Path(args.secrets_output), secret_values)

    print(
        json.dumps(
            {
                "status": "applied" if args.apply else "planned",
                "mode": args.mode,
                "catalog_version": CATALOG_VERSION,
                "public_output": str(public_path),
                "secrets_output_written": bool(secret_values),
                "resources": {
                    key: value.get("action") if isinstance(value, dict) else None
                    for key, value in report["resources"].items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

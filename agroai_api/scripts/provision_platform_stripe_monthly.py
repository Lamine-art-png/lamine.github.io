"""Provision the customer-ready monthly Platform API Stripe catalog.

Annual checkout remains deliberately disabled. Stripe Checkout currently does not
support creating mixed-interval subscriptions, while the original provisional annual
catalog combines an annual platform fee with monthly metered overages. This activator
therefore provisions only same-interval monthly base and metered prices. A future
catalog version can introduce annual billing after its entitlement and invoicing
semantics are independently implemented and proven.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import stripe

import provision_platform_stripe as base


STRIPE_API_VERSION = "2026-02-25.clover"
CONTRACT = "agroai-platform-api-stripe-monthly-provisioning-v1"
CONFIRMATIONS = {
    "test": "PROVISION AGROAI PLATFORM TEST MONTHLY BILLING",
    "live": "PROVISION AGROAI PLATFORM LIVE MONTHLY BILLING",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision the monthly AGRO-AI Platform API Stripe catalog."
    )
    parser.add_argument("--mode", choices=("test", "live"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--approve-current-catalog", action="store_true")
    parser.add_argument("--webhook-url", default=base.WEBHOOK_URL)
    parser.add_argument(
        "--public-output",
        default="platform-api-stripe-monthly-provisioning.json",
    )
    parser.add_argument(
        "--secrets-output",
        default="platform-api-stripe-monthly-secrets.env",
    )
    return parser


def _confirm(args: argparse.Namespace) -> None:
    if not args.apply:
        return
    if args.confirmation != CONFIRMATIONS[args.mode]:
        raise RuntimeError(
            f"Refusing Stripe mutation. Exact confirmation required: "
            f"{CONFIRMATIONS[args.mode]}"
        )
    if not args.approve_current_catalog:
        raise RuntimeError(
            "Refusing to provision the provisional database catalog without "
            "--approve-current-catalog."
        )


def _public_plan(plan: base.Plan) -> dict[str, Any]:
    return {
        "identifier": plan.identifier,
        "display_name": plan.display_name,
        "monthly_price_cents": plan.monthly_cents,
        "included_credits_per_month": plan.included_credits,
        "overage_price_per_1000_cents": plan.overage_cents_per_1000,
        "support_tier": plan.support_tier,
        "limits": plan.limits,
        "annual_checkout_enabled": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    _confirm(args)

    secret_key = (os.environ.get("PLATFORM_API_STRIPE_SECRET_KEY") or "").strip()
    if args.apply:
        if not secret_key:
            raise RuntimeError("PLATFORM_API_STRIPE_SECRET_KEY is required with --apply")
        base._assert_secret_mode(secret_key, args.mode)
        stripe.api_key = secret_key
        stripe.api_version = STRIPE_API_VERSION

    report: dict[str, Any] = {
        "contract": CONTRACT,
        "mode": args.mode,
        "applied": bool(args.apply),
        "stripe_api_version": STRIPE_API_VERSION,
        "catalog_version": base.CATALOG_VERSION,
        "billing_intervals_enabled": ["monthly"],
        "annual_checkout_enabled": False,
        "meter_event_name": base.METER_EVENT_NAME,
        "webhook_url": args.webhook_url,
        "approved_plans": [_public_plan(plan) for plan in base.PLANS],
        "resources": {},
        "render_env": {},
    }

    if args.apply:
        meter_id, meter_action = base._create_or_reuse_meter(True)
    else:
        meter_id, meter_action = None, "planned"
    report["resources"]["meter"] = {"id": meter_id, "action": meter_action}

    render_env: dict[str, str] = {
        "PLATFORM_API_STRIPE_MODE": args.mode,
        "PLATFORM_API_STRIPE_METER_EVENT_NAME": base.METER_EVENT_NAME,
        "PLATFORM_API_BILLING_ENABLED": "true",
        "PLATFORM_API_STRIPE_CHECKOUT_ENABLED": "true",
        "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED": "true",
        "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED": "true",
        # Public pricing stays closed because the provisional database rows still
        # contain annual offers that are intentionally not available in Checkout.
        "PLATFORM_API_PRICING_ENABLED": "false",
    }
    if meter_id:
        render_env["PLATFORM_API_STRIPE_METER_ID"] = meter_id

    for plan in base.PLANS:
        product_id, product_action = base._create_or_reuse_product(plan, args.apply)
        monthly_id, monthly_action = base._create_or_reuse_price(
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
        overage_decimal = (
            f"{plan.overage_cents_per_1000 / 1000:.12f}"
            .rstrip("0")
            .rstrip(".")
        )
        overage_id, overage_action = base._create_or_reuse_price(
            plan=plan,
            product_id=product_id,
            component="monthly_overage",
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
            "monthly_overage_price": {
                "id": overage_id,
                "action": overage_action,
                "unit_amount_decimal_cents_per_credit": overage_decimal,
            },
        }
        prefix = plan.identifier.upper()
        if monthly_id:
            render_env[f"PLATFORM_API_STRIPE_{prefix}_MONTHLY_PRICE_ID"] = monthly_id
        if overage_id:
            # The runtime's existing server catalog references this legacy config
            # key. It is safe because only monthly Checkout is exposed or proven.
            render_env[f"PLATFORM_API_STRIPE_{prefix}_OVERAGE_PRICE_ID"] = overage_id

    portal_id, portal_action = base._create_or_reuse_portal_configuration(args.apply)
    report["resources"]["customer_portal"] = {
        "id": portal_id,
        "action": portal_action,
    }
    if portal_id:
        render_env["PLATFORM_API_STRIPE_CUSTOMER_PORTAL_CONFIGURATION"] = portal_id

    webhook_id, webhook_secret, webhook_action = base._create_or_reuse_webhook(
        args.webhook_url,
        args.apply,
    )
    report["resources"]["webhook"] = {
        "id": webhook_id,
        "action": webhook_action,
        "secret_returned": bool(webhook_secret),
    }
    report["render_env"] = dict(sorted(render_env.items()))

    public_path = Path(args.public_output)
    base._write_json(public_path, report)

    secret_values: dict[str, str] = {}
    if secret_key:
        secret_values["PLATFORM_API_STRIPE_SECRET_KEY"] = secret_key
    if webhook_secret:
        secret_values["PLATFORM_API_STRIPE_WEBHOOK_SECRET"] = webhook_secret
    if secret_values:
        base._write_secrets(Path(args.secrets_output), secret_values)

    print(
        json.dumps(
            {
                "status": "applied" if args.apply else "planned",
                "mode": args.mode,
                "catalog_version": base.CATALOG_VERSION,
                "billing_intervals_enabled": ["monthly"],
                "annual_checkout_enabled": False,
                "public_output": str(public_path),
                "secrets_output_written": bool(secret_values),
                "resources": {
                    key: value.get("action")
                    if isinstance(value, dict) and "action" in value
                    else "planned" if not args.apply else "configured"
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

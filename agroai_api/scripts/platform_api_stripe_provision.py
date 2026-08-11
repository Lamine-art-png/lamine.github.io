#!/usr/bin/env python3
"""Provision provisional Platform API Stripe test resources.

Dry-run is the default. Live mode requires both --live and the exact
--confirm-live value; this script is not invoked by deployment workflows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import stripe


LIVE_CONFIRMATION = "CREATE_PLATFORM_API_LIVE_RESOURCES"
PLANS = {
    "developer": {"monthly": 14900, "annual": 143000, "overage": 75},
    "scale": {"monthly": 74900, "annual": 719000, "overage": 35},
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--apply", action="store_true", help="create resources; otherwise print a dry run")
    value.add_argument("--live", action="store_true", help="target an sk_live key")
    value.add_argument("--confirm-live", default="")
    return value


def main() -> int:
    args = parser().parse_args()
    secret = os.getenv("PLATFORM_API_STRIPE_SECRET_KEY", "")
    if args.live and (not secret.startswith("sk_live_") or args.confirm_live != LIVE_CONFIRMATION):
        print("refusing live mode: provide sk_live_ key and exact live confirmation", file=sys.stderr)
        return 2
    if not args.live and secret.startswith("sk_live_"):
        print("refusing live secret without --live and explicit confirmation", file=sys.stderr)
        return 2
    manifest = {
        "mode": "live" if args.live else "test",
        "plans": PLANS,
        "meter": {"event_name": "agroai_api_credits", "aggregation": "sum"},
        "tax_enabled": False,
    }
    if not args.apply:
        print(json.dumps({"dry_run": True, **manifest}, indent=2, sort_keys=True))
        return 0
    if not secret:
        print("PLATFORM_API_STRIPE_SECRET_KEY is required for --apply", file=sys.stderr)
        return 2
    stripe.api_key = secret
    created: dict[str, object] = {"products": {}, "prices": {}, "meter": None}
    meter = stripe.billing.Meter.create(
        display_name="AGRO-AI Platform API credits",
        event_name=manifest["meter"]["event_name"],
        default_aggregation={"formula": "sum"},
        customer_mapping={"type": "by_id", "event_payload_key": "stripe_customer_id"},
        value_settings={"event_payload_key": "value"},
        idempotency_key="agroai-api-credit-meter-v1",
    )
    created["meter"] = meter["id"]
    for identifier, prices in PLANS.items():
        product = stripe.Product.create(
            name=f"AGRO-AI Platform API {identifier.title()}",
            metadata={"billing_product": "platform_api", "plan_identifier": identifier, "provisional": "true"},
            idempotency_key=f"agroai-api-{identifier}-product-v1",
        )
        created["products"][identifier] = product["id"]
        for interval in ("monthly", "annual"):
            price = stripe.Price.create(
                product=product["id"],
                currency="usd",
                unit_amount=prices[interval],
                recurring={"interval": "month" if interval == "monthly" else "year"},
                metadata={"billing_product": "platform_api", "plan_identifier": identifier, "catalog_version": "2026-07-provisional"},
                idempotency_key=f"agroai-api-{identifier}-{interval}-v1",
            )
            created["prices"][f"{identifier}_{interval}"] = price["id"]
        overage_price = stripe.Price.create(
            product=product["id"],
            currency="usd",
            # Stripe's unit_amount_decimal is denominated in cents. The
            # provisional rate is expressed per credit here so the meter can
            # submit exact logical credit quantities.
            unit_amount_decimal=str(prices["overage"] / 1000),
            recurring={"interval": "month", "usage_type": "metered", "meter": meter["id"]},
            metadata={
                "billing_product": "platform_api",
                "plan_identifier": identifier,
                "catalog_version": "2026-07-provisional",
                "charge_type": "credit_overage",
            },
            idempotency_key=f"agroai-api-{identifier}-overage-v1",
        )
        created["prices"][f"{identifier}_overage"] = overage_price["id"]
    print(json.dumps({"dry_run": False, **manifest, "created": created}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

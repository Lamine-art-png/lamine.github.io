from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


provision = _load("platform_stripe_provision", "scripts/provision_platform_stripe.py")
configure = _load("platform_render_configure", "scripts/configure_platform_billing_render.py")


def test_approved_catalog_is_exact_and_server_authoritative():
    assert provision.CATALOG_VERSION == "2026-07-provisional"
    assert provision.METER_EVENT_NAME == "agroai_api_credits"
    assert provision.WEBHOOK_URL == (
        "https://api.agroai-pilot.com/v1/platform/billing/stripe-webhook"
    )
    plans = {plan.identifier: plan for plan in provision.PLANS}
    assert set(plans) == {"developer", "scale"}
    assert (plans["developer"].monthly_cents, plans["developer"].annual_cents) == (
        14_900,
        143_000,
    )
    assert plans["developer"].included_credits == 250_000
    assert plans["developer"].overage_cents_per_1000 == 75
    assert (plans["scale"].monthly_cents, plans["scale"].annual_cents) == (
        74_900,
        719_000,
    )
    assert plans["scale"].included_credits == 2_000_000
    assert plans["scale"].overage_cents_per_1000 == 35


def test_planning_mode_performs_no_stripe_network_calls(tmp_path, monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("planning mode attempted a Stripe mutation or read")

    monkeypatch.delenv("PLATFORM_API_STRIPE_SECRET_KEY", raising=False)
    for target in (
        provision.stripe.Product,
        provision.stripe.Price,
        provision.stripe.WebhookEndpoint,
        provision.stripe.billing.Meter,
        provision.stripe.billing_portal.Configuration,
    ):
        monkeypatch.setattr(target, "list", denied, raising=False)
        monkeypatch.setattr(target, "create", denied, raising=False)

    public = tmp_path / "plan.json"
    secrets = tmp_path / "secrets.env"
    assert (
        provision.main(
            [
                "--mode",
                "live",
                "--public-output",
                str(public),
                "--secrets-output",
                str(secrets),
            ]
        )
        == 0
    )
    payload = json.loads(public.read_text())
    assert payload["applied"] is False
    assert payload["resources"]["meter"]["action"] == "planned"
    assert payload["resources"]["developer"]["product"]["action"] == "planned"
    assert payload["resources"]["scale"]["overage_price"]["action"] == "planned"
    assert not secrets.exists()


def test_live_apply_requires_exact_operator_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_API_STRIPE_SECRET_KEY", "sk_live_example")
    with pytest.raises(RuntimeError, match="Exact confirmation"):
        provision.main(
            [
                "--mode",
                "live",
                "--apply",
                "--approve-current-catalog",
                "--public-output",
                str(tmp_path / "report.json"),
            ]
        )
    with pytest.raises(RuntimeError, match="approve-current-catalog"):
        provision.main(
            [
                "--mode",
                "live",
                "--apply",
                "--confirmation",
                provision.CONFIRMATIONS["live"],
                "--public-output",
                str(tmp_path / "report.json"),
            ]
        )


def test_key_mode_mismatch_fails_before_stripe_call(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_example")
    with pytest.raises(RuntimeError, match="mode mismatch"):
        provision.main(
            [
                "--mode",
                "live",
                "--apply",
                "--approve-current-catalog",
                "--confirmation",
                provision.CONFIRMATIONS["live"],
                "--public-output",
                str(tmp_path / "report.json"),
            ]
        )


def test_overage_decimal_is_per_credit_and_exact(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(provision, "_list_prices", lambda _product: [])
    monkeypatch.setattr(
        provision.stripe.Price,
        "create",
        lambda **kwargs: calls.append(kwargs) or {"id": "price_overage"},
    )
    plan = next(plan for plan in provision.PLANS if plan.identifier == "developer")
    price_id, action = provision._create_or_reuse_price(
        plan=plan,
        product_id="prod_developer",
        component="overage",
        interval="month",
        amount_cents=None,
        amount_decimal_cents="0.075",
        usage_type="metered",
        meter_id="mtr_credits",
        apply=True,
    )
    assert (price_id, action) == ("price_overage", "created")
    assert calls == [
        {
            "currency": "usd",
            "product": "prod_developer",
            "recurring": {
                "interval": "month",
                "usage_type": "metered",
                "meter": "mtr_credits",
            },
            "metadata": {
                "agroai_product": "platform_api",
                "catalog_version": "2026-07-provisional",
                "plan_identifier": "developer",
                "billing_component": "overage",
            },
            "nickname": "Developer overage",
            "lookup_key": "agroai_platform_developer_overage_2026_07_provisional",
            "unit_amount_decimal": "0.075",
        }
    ]


def test_render_configuration_requires_complete_applied_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "contract": "agroai-platform-api-stripe-provisioning-v1",
                "mode": "live",
                "applied": False,
                "render_env": {},
            }
        )
    )
    secrets = tmp_path / "secrets.env"
    secrets.write_text("PLATFORM_API_STRIPE_SECRET_KEY=sk_live_example\n")
    os.chmod(secrets, stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(RuntimeError, match="planning-only"):
        configure.main(
            [
                "--mode",
                "live",
                "--provisioning-report",
                str(report),
                "--secrets-file",
                str(secrets),
            ]
        )


def test_render_configuration_never_accepts_broad_secret_permissions(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "contract": "agroai-platform-api-stripe-provisioning-v1",
                "mode": "live",
                "applied": True,
                "render_env": {key: "configured" for key in configure.REQUIRED_ENV_KEYS},
            }
        )
    )
    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        "PLATFORM_API_STRIPE_SECRET_KEY=sk_live_example\n"
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET=whsec_example\n"
    )
    os.chmod(secrets, 0o644)
    with pytest.raises(RuntimeError, match="permissions"):
        configure.main(
            [
                "--mode",
                "live",
                "--provisioning-report",
                str(report),
                "--secrets-file",
                str(secrets),
            ]
        )


def test_render_mutation_allowlist_is_narrow():
    assert configure.ALLOWED_ENV_KEYS
    assert configure.SECRET_ENV_KEYS == {
        "PLATFORM_API_STRIPE_SECRET_KEY",
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
    }
    assert all(key.startswith("PLATFORM_API_") for key in configure.ALLOWED_ENV_KEYS)
    assert all(key.startswith("PLATFORM_API_") for key in configure.SECRET_ENV_KEYS)

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load("provision_platform_stripe", "scripts/provision_platform_stripe.py")
monthly = _load(
    "provision_platform_stripe_monthly",
    "scripts/provision_platform_stripe_monthly.py",
)
configure = _load(
    "configure_platform_billing_render_monthly",
    "scripts/configure_platform_billing_render_monthly.py",
)


def test_approved_monthly_catalog_is_exact():
    assert base.CATALOG_VERSION == "2026-07-provisional"
    assert base.METER_EVENT_NAME == "agroai_api_credits"
    assert monthly.STRIPE_API_VERSION == "2026-02-25.clover"
    assert monthly.CONTRACT == "agroai-platform-api-stripe-monthly-provisioning-v1"
    plans = {plan.identifier: plan for plan in base.PLANS}
    assert set(plans) == {"developer", "scale"}
    assert plans["developer"].monthly_cents == 14_900
    assert plans["developer"].included_credits == 250_000
    assert plans["developer"].overage_cents_per_1000 == 75
    assert plans["scale"].monthly_cents == 74_900
    assert plans["scale"].included_credits == 2_000_000
    assert plans["scale"].overage_cents_per_1000 == 35


def test_planning_mode_performs_no_stripe_network_calls(tmp_path, monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("planning mode attempted a Stripe mutation or read")

    monkeypatch.delenv("PLATFORM_API_STRIPE_SECRET_KEY", raising=False)
    for target in (
        base.stripe.Product,
        base.stripe.Price,
        base.stripe.WebhookEndpoint,
        base.stripe.billing.Meter,
        base.stripe.billing_portal.Configuration,
    ):
        monkeypatch.setattr(target, "list", denied, raising=False)
        monkeypatch.setattr(target, "create", denied, raising=False)

    public = tmp_path / "plan.json"
    secrets = tmp_path / "secrets.env"
    assert monthly.main(
        [
            "--mode",
            "live",
            "--public-output",
            str(public),
            "--secrets-output",
            str(secrets),
        ]
    ) == 0
    payload = json.loads(public.read_text())
    assert payload["applied"] is False
    assert payload["billing_intervals_enabled"] == ["monthly"]
    assert payload["annual_checkout_enabled"] is False
    assert payload["render_env"]["PLATFORM_API_PRICING_ENABLED"] == "false"
    assert "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID" not in payload["render_env"]
    assert "PLATFORM_API_STRIPE_SCALE_ANNUAL_PRICE_ID" not in payload["render_env"]
    assert payload["resources"]["meter"]["action"] == "planned"
    assert not secrets.exists()


def test_live_apply_requires_exact_operator_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_API_STRIPE_SECRET_KEY", "sk_live_example")
    with pytest.raises(RuntimeError, match="Exact confirmation"):
        monthly.main(
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
        monthly.main(
            [
                "--mode",
                "live",
                "--apply",
                "--confirmation",
                monthly.CONFIRMATIONS["live"],
                "--public-output",
                str(tmp_path / "report.json"),
            ]
        )


def test_key_mode_mismatch_fails_before_stripe_call(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_example")
    with pytest.raises(RuntimeError, match="mode mismatch"):
        monthly.main(
            [
                "--mode",
                "live",
                "--apply",
                "--approve-current-catalog",
                "--confirmation",
                monthly.CONFIRMATIONS["live"],
                "--public-output",
                str(tmp_path / "report.json"),
            ]
        )


def test_monthly_overage_decimal_is_exact(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(base, "_list_prices", lambda _product: [])
    monkeypatch.setattr(
        base.stripe.Price,
        "create",
        lambda **kwargs: calls.append(kwargs) or {"id": "price_overage"},
    )
    plan = next(plan for plan in base.PLANS if plan.identifier == "developer")
    price_id, action = base._create_or_reuse_price(
        plan=plan,
        product_id="prod_developer",
        component="monthly_overage",
        interval="month",
        amount_cents=None,
        amount_decimal_cents="0.075",
        usage_type="metered",
        meter_id="mtr_credits",
        apply=True,
    )
    assert (price_id, action) == ("price_overage", "created")
    assert calls[0]["unit_amount_decimal"] == "0.075"
    assert calls[0]["recurring"] == {
        "interval": "month",
        "usage_type": "metered",
        "meter": "mtr_credits",
    }
    assert calls[0]["lookup_key"] == (
        "agroai_platform_developer_monthly_overage_2026_07_provisional"
    )


def _complete_report() -> dict:
    return {
        "contract": monthly.CONTRACT,
        "mode": "live",
        "applied": True,
        "billing_intervals_enabled": ["monthly"],
        "annual_checkout_enabled": False,
        "render_env": {
            key: "false" if key == "PLATFORM_API_PRICING_ENABLED" else "configured"
            for key in configure.REQUIRED_PUBLIC_KEYS
        },
    }


def test_render_configuration_requires_applied_monthly_report(tmp_path):
    report = tmp_path / "report.json"
    payload = _complete_report()
    payload["applied"] = False
    report.write_text(json.dumps(payload))
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


def test_render_configuration_rejects_annual_or_public_pricing(tmp_path):
    report = tmp_path / "report.json"
    payload = _complete_report()
    payload["annual_checkout_enabled"] = True
    report.write_text(json.dumps(payload))
    secrets = tmp_path / "secrets.env"
    secrets.write_text("PLATFORM_API_STRIPE_SECRET_KEY=sk_live_example\n")
    os.chmod(secrets, stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(RuntimeError, match="Annual Checkout"):
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

    payload = _complete_report()
    payload["render_env"]["PLATFORM_API_PRICING_ENABLED"] = "true"
    report.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="non-public"):
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
    report.write_text(json.dumps(_complete_report()))
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


def test_customer_surface_and_workflow_keep_annual_checkout_closed():
    page = (
        REPOSITORY_ROOT
        / "figma-enterprise-v4/src/app/components/PlatformBillingPage.tsx"
    ).read_text()
    workflow = (
        REPOSITORY_ROOT
        / ".github/workflows/platform-api-stripe-activation.yml"
    ).read_text()
    assert 'billing_interval: "monthly"' in page
    assert "monthlyPriceCents: 14_900" in page
    assert "monthlyPriceCents: 74_900" in page
    assert "Annual" not in page
    assert "provision_platform_stripe_monthly.py" in workflow
    assert "configure_platform_billing_render_monthly.py" in workflow
    assert 'billing_interval\":\"monthly' in workflow
    assert 'billing_interval\":\"annual' not in workflow


def test_render_mutation_allowlist_is_narrow():
    assert configure.PUBLIC_KEYS
    assert configure.SECRET_KEYS == {
        "PLATFORM_API_STRIPE_SECRET_KEY",
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
    }
    assert all(key.startswith("PLATFORM_API_") for key in configure.PUBLIC_KEYS)
    assert all(key.startswith("PLATFORM_API_") for key in configure.SECRET_KEYS)
    assert not any("ANNUAL" in key for key in configure.PUBLIC_KEYS)

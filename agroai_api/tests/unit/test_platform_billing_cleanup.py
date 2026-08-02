from __future__ import annotations

import json
from types import SimpleNamespace

from app.api.v1.platform_billing import (
    _checkout_subscription_reusable,
    billing_readiness,
)


def test_abandoned_checkout_without_stripe_subscription_is_reusable():
    row = SimpleNamespace(status="checkout_pending", stripe_subscription_id=None)
    assert _checkout_subscription_reusable(row) is True


def test_canceled_checkout_without_stripe_subscription_is_reusable():
    row = SimpleNamespace(status="canceled", stripe_subscription_id="")
    assert _checkout_subscription_reusable(row) is True


def test_stripe_mapped_or_active_subscription_is_never_reusable():
    assert _checkout_subscription_reusable(
        SimpleNamespace(status="checkout_pending", stripe_subscription_id="sub_live_123")
    ) is False
    assert _checkout_subscription_reusable(
        SimpleNamespace(status="active", stripe_subscription_id=None)
    ) is False


def test_billing_readiness_never_exposes_configured_secret_values(monkeypatch):
    secrets = {
        "PLATFORM_API_STRIPE_SECRET_KEY": "sk_live_super_secret_value",
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET": "whsec_super_secret_value",
        "PLATFORM_API_STRIPE_METER_ID": "mtr_secret_identifier",
        "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID": "price_secret_dev_month",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    rendered = json.dumps(billing_readiness(), sort_keys=True)
    for value in secrets.values():
        assert value not in rendered
    assert "missing" in rendered
    assert "invalid" in rendered

from __future__ import annotations

from datetime import datetime, timedelta

from app.api.v1 import platform_billing
from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import PlatformApiSubscription
from tests.unit.test_platform_api_billing_product import _developer_plan, _enable_checkout
from tests.unit.test_platform_api_foundation import _project_and_key


def _authorization(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}


def test_expired_checkout_releases_the_local_subscription_slot(
    client,
    db,
    monkeypatch,
):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    plan = _developer_plan(db)
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="checkout_pending",
        status_slot="active",
        billing_mode="stripe",
        billing_interval="monthly",
        stripe_customer_id="cus_expired_checkout",
    )
    db.add(subscription)
    db.commit()

    monkeypatch.setattr(settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_MODE", "test")
    monkeypatch.setattr(
        settings,
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
        "whsec_platform_api",
    )
    event = {
        "id": "evt_checkout_expired",
        "type": "checkout.session.expired",
        "created": 2_000_000_000,
        "livemode": False,
        "data": {
            "object": {
                "object": "checkout.session",
                "id": "cs_expired",
                "customer": "cus_expired_checkout",
                "client_reference_id": organization.id,
                "metadata": {
                    "organization_id": organization.id,
                    "api_subscription_id": subscription.id,
                    "billing_product": "platform_api",
                },
            }
        },
    }
    monkeypatch.setattr(
        platform_billing.stripe.Webhook,
        "construct_event",
        lambda *_args, **_kwargs: event,
    )

    response = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"{}",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    db.refresh(subscription)
    assert subscription.status == "checkout_expired"
    assert subscription.stripe_state_updated_at == datetime.utcfromtimestamp(
        event["created"]
    )

    _enable_checkout(monkeypatch)
    monkeypatch.setattr(
        platform_billing.stripe.checkout.Session,
        "create",
        lambda **_kwargs: {
            "id": "cs_retry",
            "url": "https://checkout.stripe.test/retry",
        },
    )
    checkout = client.post(
        "/v1/platform/developer/billing/checkout",
        headers={
            **_authorization(user),
            "Idempotency-Key": "retry-after-expiry",
        },
        json={"plan": "developer", "billing_interval": "monthly"},
    )

    assert checkout.status_code == 200
    db.refresh(subscription)
    assert subscription.status == "checkout_pending"
    assert subscription.stripe_state_updated_at is None


def test_canceled_subscription_can_resubscribe_without_old_stripe_mapping(
    client,
    db,
    monkeypatch,
):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    organization.stripe_customer_id = "cus_returning"
    plan = _developer_plan(db)
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="canceled",
        status_slot="active",
        billing_mode="stripe",
        billing_interval="monthly",
        stripe_customer_id="cus_returning",
        stripe_subscription_id="sub_old",
        current_period_start=datetime.utcnow() - timedelta(days=30),
        current_period_end=datetime.utcnow() - timedelta(days=1),
        grace_ends_at=datetime.utcnow() - timedelta(days=1),
        stripe_state_updated_at=datetime.utcnow() - timedelta(days=1),
        cancel_at_period_end=True,
    )
    db.add(subscription)
    db.commit()

    _enable_checkout(monkeypatch)
    monkeypatch.setattr(
        platform_billing.stripe.checkout.Session,
        "create",
        lambda **_kwargs: {
            "id": "cs_returning",
            "url": "https://checkout.stripe.test/returning",
        },
    )

    response = client.post(
        "/v1/platform/developer/billing/checkout",
        headers={
            **_authorization(user),
            "Idempotency-Key": "returning-subscription",
        },
        json={"plan": "developer", "billing_interval": "monthly"},
    )

    assert response.status_code == 200
    db.refresh(subscription)
    assert subscription.status == "checkout_pending"
    assert subscription.stripe_subscription_id is None
    assert subscription.current_period_start is None
    assert subscription.current_period_end is None
    assert subscription.grace_ends_at is None
    assert subscription.stripe_state_updated_at is None
    assert subscription.cancel_at_period_end is False

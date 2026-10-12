"""Authoritative paid-checkout to Platform API access contract.

All Stripe identities/events in these tests are synthetic. They do not create
charges or assert that a real production transaction has occurred.
"""
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api.v1 import platform_billing
from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import (
    PlatformApiSubscription,
    PlatformCheckoutIdempotency,
    PlatformLiveAccessRequest,
)
from app.platform_api.programs import require_api_entitlement
from tests.unit.test_platform_api_billing_product import _developer_plan, _enable_checkout
from tests.unit.test_platform_api_foundation import _project_and_key


def _approval(db, org, user):
    row = PlatformLiveAccessRequest(
        organization_id=org.id,
        requested_by_user_id=user.id,
        api_project_id=None,
        status="approved",
        intended_production_use="Read-only agricultural data access",
        expected_users="2",
        expected_volume="1000",
        expected_peak_rate="2",
        data_categories_json=[],
        provider_dependencies_json=[],
        geographic_regions_json=[],
        security_contact=user.email,
        incident_contact=user.email,
        cidr_strategy="restricted",
        data_retention="30 days",
        billing_plan="developer",
        decided_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return row


def _checkout_setup(client, db, monkeypatch):
    user, org, *_ = _project_and_key(db)
    org.verification_status = "approved"
    db.commit()
    _developer_plan(db)
    _enable_checkout(monkeypatch)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_MODE", "test")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_WEBHOOK_SECRET", "whsec_fixture")
    monkeypatch.setattr(platform_billing.stripe.Customer, "create", lambda **kwargs: {"id": "cus_fixture"})
    created = []
    def fake_checkout(**kwargs):
        created.append(kwargs)
        return {"id": "cs_fixture", "url": "https://checkout.stripe.com/c/pay/fixture"}
    monkeypatch.setattr(platform_billing.stripe.checkout.Session, "create", fake_checkout)
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': user.id})}",
        "Idempotency-Key": "checkout-fixture-1",
    }
    return user, org, headers, created


def _webhook(client, monkeypatch, *, event_id, event_type, created, obj):
    event = {
        "id": event_id,
        "type": event_type,
        "created": created,
        "livemode": False,
        "data": {"object": obj},
    }
    monkeypatch.setattr(
        platform_billing.stripe.Webhook, "construct_event",
        lambda *_args, **_kwargs: event,
    )
    return client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "synthetic-fixture"},
        content=b"{}",
    )


def test_production_rejects_checkout_before_live_approval_and_never_calls_stripe(client, db, monkeypatch):
    _user, _org, headers, created = _checkout_setup(client, db, monkeypatch)
    response = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=headers,
        json={"plan": "developer", "billing_interval": "monthly"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_live_access_approval_required"
    assert created == []
    assert db.query(PlatformCheckoutIdempotency).count() == 0


def test_paid_checkout_activates_live_access_only_after_signed_payment(client, db, monkeypatch):
    user, org, headers, created = _checkout_setup(client, db, monkeypatch)
    _approval(db, org, user)
    result = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=headers,
        json={"plan": "developer", "billing_interval": "monthly"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["checkout_url"].startswith("https://checkout.stripe.com/")
    assert len(created) == 1
    assert created[0]["line_items"][0]["quantity"] == 1
    subscription = db.query(PlatformApiSubscription).filter_by(organization_id=org.id).one()
    assert subscription.status == "checkout_pending"

    with pytest.raises(HTTPException) as blocked:
        require_api_entitlement(
            db, org, environment="live", operation="api_key_authentication", api_project_id=None,
        )
    assert blocked.value.detail["code"] == "api_subscription_ineligible"

    metadata = {
        **created[0]["metadata"],
        "billing_product": "platform_api",
    }
    unpaid = _webhook(
        client, monkeypatch, event_id="evt_checkout_unpaid_fixture",
        event_type="checkout.session.completed", created=2_000_000_000,
        obj={
            "object": "checkout.session", "id": "cs_fixture",
            "customer": "cus_fixture", "subscription": "sub_fixture",
            "payment_status": "unpaid", "metadata": metadata,
            "client_reference_id": org.id,
        },
    )
    assert unpaid.status_code == 200, unpaid.text
    assert unpaid.json()["status"] == "processed"
    db.refresh(subscription)
    assert subscription.status == "checkout_pending"

    no_payment = _webhook(
        client, monkeypatch, event_id="evt_checkout_nopayment_fixture",
        event_type="checkout.session.completed", created=2_000_000_001,
        obj={
            "object": "checkout.session", "id": "cs_fixture",
            "customer": "cus_fixture", "subscription": "sub_fixture",
            "payment_status": "no_payment_required", "metadata": metadata,
            "client_reference_id": org.id,
        },
    )
    assert no_payment.status_code == 200
    db.refresh(subscription)
    assert subscription.status == "checkout_pending"

    paid = _webhook(
        client, monkeypatch, event_id="evt_checkout_paid_fixture",
        event_type="checkout.session.completed", created=2_000_000_002,
        obj={
            "object": "checkout.session", "id": "cs_fixture",
            "customer": "cus_fixture", "subscription": "sub_fixture",
            "payment_status": "paid", "metadata": metadata,
            "client_reference_id": org.id,
        },
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "processed"
    db.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.stripe_subscription_id == "sub_fixture"

    enrollment, authorized = require_api_entitlement(
        db, org, environment="live", operation="api_key_authentication", api_project_id=None,
    )
    assert "live" in enrollment.allowed_environments_json
    assert authorized.id == subscription.id

    duplicate = _webhook(
        client, monkeypatch, event_id="evt_checkout_paid_fixture",
        event_type="checkout.session.completed", created=2_000_000_002,
        obj={"metadata": metadata},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

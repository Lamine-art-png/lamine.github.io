import json

import pytest
from fastapi import HTTPException

from app.api.v1 import billing
from app.core.config import settings
from app.models.saas import BillingEvent, Organization, OrganizationMembership
from app.services.commercial_billing_lifecycle import apply_authoritative_billing_event
from tests.unit.test_saas_foundation import _stripe_signature, _verify_and_login


PRICES = {
    ("professional", "monthly"): "STRIPE_PRICE_PRO_MONTHLY",
    ("professional", "annual"): "STRIPE_PRICE_PRO_ANNUAL",
    ("team", "monthly"): "STRIPE_PRICE_TEAM_MONTHLY",
    ("team", "annual"): "STRIPE_PRICE_TEAM_ANNUAL",
    ("network", "monthly"): "STRIPE_PRICE_NETWORK_MONTHLY",
    ("network", "annual"): "STRIPE_PRICE_NETWORK_ANNUAL",
}


@pytest.mark.parametrize("plan,period", PRICES)
def test_authoritative_checkout_uses_server_price_and_reuses_session(client, db, monkeypatch, plan, period):
    body, headers = _verify_and_login(client, db)
    org_id = body["current_organization"]["id"]
    for (configured_plan, configured_period), setting in PRICES.items():
        monkeypatch.setattr(settings, setting, f"price_{configured_plan}_{configured_period}")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    monkeypatch.setattr(billing.stripe.Customer, "create", lambda **kwargs: {"id": "cus_local"})
    calls = []

    def make_session(**kwargs):
        calls.append(kwargs)
        return {"id": "cs_local", "url": "https://checkout.stripe.test/local", "expires_at": 4102444800}

    monkeypatch.setattr(billing.stripe.checkout.Session, "create", make_session)
    payload = {"plan_id": plan, "billing_period": period, "locale": "pt-BR", "price_id": "price_attacker", "amount": 1}
    first = client.post("/v1/billing/checkout-authoritative", headers=headers, json=payload)
    second = client.post("/v1/billing/checkout-authoritative", headers=headers, json=payload)
    assert first.status_code == second.status_code == 200, first.text
    assert len(calls) == 1
    request = calls[0]
    assert request["line_items"] == [{"price": f"price_{plan}_{period}", "quantity": 1}]
    assert request["locale"] == "pt-BR"
    assert request["metadata"]["organization_id"] == org_id
    assert request["metadata"]["plan"] == plan
    assert request["metadata"]["billing_period"] == period
    assert request["subscription_data"]["metadata"] == request["metadata"]
    assert "session_id={CHECKOUT_SESSION_ID}" in request["success_url"]
    assert request["success_url"].startswith("https://app.agroai-pilot.com/billing")
    assert db.get(Organization, org_id).plan == "free"


def test_late_deleted_subscription_cannot_downgrade_replacement():
    class Org:
        id = "org_local"
        plan = "team"
        customer_class = "individual_operator"
        organization_type = None
        subscription_source = "stripe"
        stripe_customer_id = "cus_local"
        stripe_subscription_id = "sub_new"
        subscription_status = "active"

    org = Org()
    apply_authoritative_billing_event(None, org, "customer.subscription.deleted", {"id": "sub_old", "customer": "cus_local"})
    assert (org.plan, org.subscription_status, org.stripe_subscription_id) == ("team", "active", "sub_new")


def test_checkout_redirect_without_active_subscription_grants_nothing(client, db, monkeypatch):
    body, headers = _verify_and_login(client, db)
    org_id = body["current_organization"]["id"]
    org = db.get(Organization, org_id)
    org.stripe_customer_id = "cus_local"
    db.commit()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    monkeypatch.setattr(billing.stripe.checkout.Session, "retrieve", lambda session_id: {
        "id": session_id, "status": "open", "customer": "cus_local", "metadata": {"organization_id": org_id}
    })
    response = client.post("/v1/billing/reconcile-checkout", headers=headers, json={"organization_id": org_id, "session_id": "cs_local"})
    assert response.status_code == 200
    assert response.json()["status"] == "confirming"
    assert db.get(Organization, org_id).plan == "free"


def test_reconciliation_activates_only_the_matching_stripe_subscription(client, db, monkeypatch):
    body, headers = _verify_and_login(client, db)
    org_id = body["current_organization"]["id"]
    org = db.get(Organization, org_id)
    org.stripe_customer_id = "cus_local"
    db.commit()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    monkeypatch.setattr(settings, "STRIPE_PRICE_TEAM_MONTHLY", "price_team_local")
    monkeypatch.setattr(billing.stripe.checkout.Session, "retrieve", lambda session_id: {
        "id": session_id, "status": "complete", "customer": "cus_local", "subscription": "sub_local",
        "metadata": {"organization_id": org_id}
    })
    monkeypatch.setattr(billing.stripe.Subscription, "retrieve", lambda _subscription_id: {
        "id": "sub_local", "customer": "cus_local", "status": "active", "metadata": {"plan": "network"},
        "items": {"data": [{"price": {"id": "price_team_local"}}]},
    })
    response = client.post("/v1/billing/reconcile-checkout", headers=headers, json={"organization_id": org_id, "session_id": "cs_local"})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "active", "plan": "team"}
    assert db.get(Organization, org_id).stripe_subscription_id == "sub_local"

    forbidden = client.post("/v1/billing/reconcile-checkout", headers=headers, json={"organization_id": org_id, "session_id": "bad_session"})
    assert forbidden.status_code == 422


def test_old_invoice_failure_cannot_mark_new_subscription_past_due():
    from types import SimpleNamespace
    org = SimpleNamespace(id="org_local", plan="team", customer_class="individual_operator", organization_type=None,
                          subscription_status="active", stripe_subscription_id="sub_new")
    apply_authoritative_billing_event(None, org, "invoice.payment_failed", {"subscription": "sub_old"})
    assert org.subscription_status == "active"
    apply_authoritative_billing_event(None, org, "invoice.payment_failed", {
        "parent": {"type": "subscription_details", "subscription_details": {"subscription": "sub_new"}}
    })
    assert org.subscription_status == "past_due"


def test_subscription_metadata_cannot_grant_paid_access_without_known_price():
    from types import SimpleNamespace
    org = SimpleNamespace(id="org_local", plan="free", customer_class="individual_operator", organization_type=None,
                          subscription_status="inactive", stripe_subscription_id=None, stripe_customer_id=None,
                          subscription_source="local", stripe_price_id=None, stripe_product_id=None,
                          current_period_start=None, current_period_end=None, cancel_at_period_end=False)
    apply_authoritative_billing_event(None, org, "customer.subscription.created", {
        "id": "sub_local", "customer": "cus_local", "status": "active", "metadata": {"plan": "network"},
        "items": {"data": []},
    })
    assert org.plan == "free"


def test_webhook_contract_includes_subscription_updated():
    assert {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated",
            "customer.subscription.deleted", "invoice.payment_failed"} <= billing.WEBHOOK_EVENTS


def test_live_checkout_rejects_test_key_or_mispriced_catalog(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    with pytest.raises(HTTPException) as test_key:
        billing._stripe_ready()
    assert test_key.value.status_code == 503

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_live_local")
    monkeypatch.setattr(settings, "APP_URL", "https://app.agroai-pilot.com")
    monkeypatch.setattr(billing.stripe.Price, "retrieve", lambda _price_id: {
        "id": "price_wrong", "active": True, "livemode": True, "currency": "usd",
        "unit_amount": 1, "recurring": {"interval": "month", "interval_count": 1},
    })
    with pytest.raises(HTTPException) as wrong_price:
        billing._validate_live_offer("professional_monthly", {"price": "price_wrong"})
    assert wrong_price.value.status_code == 503


def test_subscription_price_change_and_cancellation_follow_stripe(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_MONTHLY", "price_pro_local")
    monkeypatch.setattr(settings, "STRIPE_PRICE_TEAM_ANNUAL", "price_team_local")
    org = SimpleNamespace(id="org_local", plan="free", customer_class="individual_operator", organization_type=None,
                          subscription_status="inactive", stripe_subscription_id=None, stripe_customer_id=None,
                          subscription_source="local", stripe_price_id=None, stripe_product_id=None,
                          current_period_start=None, current_period_end=None, cancel_at_period_end=False)
    base = {"id": "sub_local", "customer": "cus_local", "status": "active", "current_period_start": 1800000000,
            "current_period_end": 1802592000, "items": {"data": [{"price": {"id": "price_pro_local"}}]}}
    apply_authoritative_billing_event(None, org, "customer.subscription.created", base)
    assert (org.plan, org.subscription_status) == ("professional", "active")
    updated = {**base, "items": {"data": [{"price": {"id": "price_team_local"}}]},
               "metadata": {"plan": "professional"}, "current_period_end": 1834128000}
    apply_authoritative_billing_event(None, org, "customer.subscription.updated", updated)
    assert (org.plan, org.stripe_price_id, org.current_period_end.year) == ("team", "price_team_local", 2028)
    apply_authoritative_billing_event(None, org, "customer.subscription.deleted", updated)
    assert (org.plan, org.subscription_status) == ("free", "canceled")


def test_customer_portal_uses_only_membership_customer(client, db, monkeypatch):
    owner, owner_headers = _verify_and_login(client, db, "billing-owner@example.com", "Owner Farm")
    _other, other_headers = _verify_and_login(client, db, "billing-other@example.com", "Other Farm")
    org_id = owner["current_organization"]["id"]
    org = db.get(Organization, org_id)
    org.stripe_customer_id = "cus_owner"
    db.commit()
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    calls = []

    def portal(**kwargs):
        calls.append(kwargs)
        return {"url": "https://billing.stripe.test/portal"}

    monkeypatch.setattr(billing.stripe.billing_portal.Session, "create", portal)
    rejected = client.post("/v1/billing/create-portal-session", headers=other_headers,
                           json={"organization_id": org_id, "locale": "pt-BR"})
    assert rejected.status_code == 404
    assert calls == []
    accepted = client.post("/v1/billing/create-portal-session", headers=owner_headers,
                           json={"organization_id": org_id, "locale": "pt-BR"})
    assert accepted.status_code == 200, accepted.text
    assert calls == [{"customer": "cus_owner", "return_url": "https://app.agroai-pilot.com/billing", "locale": "pt-BR"}]

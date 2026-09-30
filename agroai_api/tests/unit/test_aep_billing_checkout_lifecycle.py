import json

import pytest

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

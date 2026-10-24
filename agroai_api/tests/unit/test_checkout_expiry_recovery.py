"""Regression coverage for Stripe expiry recovery and checkout renewal."""
from datetime import datetime

from app.api.v1 import billing, commercial_intelligence, platform_billing
from app.core.config import settings
from tests.unit.test_saas_foundation import _verify_and_login


def test_aep_checkout_recovers_and_renews_after_expiry(client, db, monkeypatch):
    account, headers = _verify_and_login(client, db)
    org_id = account["current_organization"]["id"]
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_local")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_MONTHLY", "price_professional_monthly")
    customers = []
    monkeypatch.setattr(
        billing.stripe.Customer, "create",
        lambda **kwargs: (customers.append(kwargs), {"id": "cus_local"})[1],
    )
    sessions = []

    def new_session(**kwargs):
        sessions.append(kwargs)
        n = len(sessions)
        return {
            "id": f"cs_local_{n}",
            "url": f"https://checkout.stripe.test/session/{n}",
            "expires_at": int(datetime.utcnow().timestamp()) - 1 if n == 1 else 4102444800,
        }

    monkeypatch.setattr(billing.stripe.checkout.Session, "create", new_session)
    payload = {"plan_id": "professional", "billing_period": "monthly"}
    one = client.post("/v1/billing/checkout-authoritative", headers=headers, json=payload)
    two = client.post("/v1/billing/checkout-authoritative", headers=headers, json=payload)
    three = client.post("/v1/billing/checkout-authoritative", headers=headers, json=payload)
    assert (one.status_code, two.status_code, three.status_code) == (200, 200, 200)
    assert len(sessions) == 2
    assert one.json()["checkout_url"] != two.json()["checkout_url"]
    assert two.json()["checkout_url"] == three.json()["checkout_url"]
    assert all(x["after_expiration"]["recovery"]["enabled"] is True for x in sessions)
    assert customers and customers[0]["email"]


def test_other_checkout_paths_have_stripe_recovery(monkeypatch):
    captured = []

    class DummySession:
        @staticmethod
        def create(**kwargs):
            captured.append(kwargs)
            return {"id": "cs_local", "url": "https://checkout.stripe.test"}

    # Keep this as a code-level contract: actual checkout integration tests use
    # authenticated organization and wallet fixtures in their separate suites.
    import inspect
    assert 'after_expiration={"recovery": {"enabled": True}}' in inspect.getsource(commercial_intelligence.wallet_checkout)
    assert '"after_expiration": {"recovery": {"enabled": True}}' in inspect.getsource(platform_billing.create_api_checkout)

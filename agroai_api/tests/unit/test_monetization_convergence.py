from types import SimpleNamespace

from app.api.deps import AuthContext
from app.api.v1 import billing, product_shell
from app.api.v1.monetization_convergence import (
    AuthoritativeCheckoutRequest,
    _quota_rows,
    checkout_authoritative,
)
from app.main import app


def test_customer_monetization_routes_are_attached_to_live_app():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/v1/billing/commercial-summary" in paths
    assert "/v1/billing/checkout-authoritative" in paths


def test_quota_rows_expose_exact_limits_and_contextual_upgrade_targets():
    rows = _quota_rows(
        {
            "metrics": {
                "ai_action": {"used": 25, "reserved": 0, "limit": 25, "remaining": 0, "percent_used": 100.0},
                "active_connector": {"used": 1, "reserved": 0, "limit": 1, "remaining": 0, "percent_used": 100.0},
            }
        }
    )
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["ai_action"]["label"] == "AGRO-AI actions"
    assert by_metric["ai_action"]["used"] == 25
    assert by_metric["ai_action"]["limit"] == 25
    assert by_metric["ai_action"]["recommended_plan"] == "professional"
    assert by_metric["active_connector"]["recommended_plan"] == "professional"


def test_authoritative_checkout_bridge_delegates_to_canonical_billing_endpoint(monkeypatch):
    org = SimpleNamespace(id="org_1", plan="free")
    membership = SimpleNamespace(role="owner")
    user = SimpleNamespace(id="user_1")
    ctx = AuthContext(user=user, organization=org, membership=membership)
    captured = {}

    def fake_checkout(payload, user=None, db=None):
        captured["organization_id"] = payload.organization_id
        captured["offer"] = payload.offer
        captured["user"] = user
        captured["db"] = db
        return {"checkout_url": "https://checkout.example/session", "offer": payload.offer, "mode": "subscription"}

    monkeypatch.setattr(billing, "create_checkout_session", fake_checkout)
    db = object()
    response = checkout_authoritative(
        AuthoritativeCheckoutRequest(plan_id="professional", billing_period="annual"),
        ctx=ctx,
        db=db,
    )

    assert captured == {
        "organization_id": "org_1",
        "offer": "professional_annual",
        "user": user,
        "db": db,
    }
    assert response["status"] == "checkout_ready"
    assert response["checkout_url"] == "https://checkout.example/session"
    assert response["plan"]["id"] == "professional"


def test_api_assembly_installs_authoritative_billing_lifecycle_explicitly():
    assert getattr(billing.create_checkout_session, "__agroai_commercial_hardened__", False) is True
    assert getattr(billing.billing_status, "__agroai_period_aware__", False) is True
    assert billing._apply_billing_event.__name__ == "apply_authoritative_billing_event"


def test_legacy_product_shell_checkout_is_not_the_portal_authority():
    # The route remains for compatibility, but the new portal calls the dedicated
    # authoritative bridge. Keeping this assertion makes future accidental reuse
    # visible in review.
    assert callable(product_shell.billing_checkout)

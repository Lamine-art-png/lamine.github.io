from types import SimpleNamespace

from app.api.deps import AuthContext
from app.api.v1 import billing, product_shell
from app.api.v1.monetization_convergence import (
    AuthoritativeCheckoutRequest,
    _quota_rows,
    _set_cardinality,
    checkout_authoritative,
)
from app.main import app
from app.services.commercial_billing_lifecycle import install_commercial_billing_lifecycle


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


def test_cardinality_reconciliation_replaces_event_totals_with_live_capacity():
    snapshot = {
        "metrics": {
            "seat": {"used": 0, "reserved": 4, "limit": 10, "remaining": 6, "percent_used": 0.0},
            "managed_entity": {"used": 0, "reserved": 0, "limit": None, "remaining": None, "percent_used": None},
        }
    }
    _set_cardinality(snapshot, "seat", 8)
    _set_cardinality(snapshot, "managed_entity", 42)
    assert snapshot["metrics"]["seat"]["used"] == 8
    assert snapshot["metrics"]["seat"]["reserved"] == 0
    assert snapshot["metrics"]["seat"]["remaining"] == 2
    assert snapshot["metrics"]["seat"]["percent_used"] == 80.0
    assert snapshot["metrics"]["managed_entity"]["used"] == 42
    assert snapshot["metrics"]["managed_entity"]["remaining"] is None


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


def test_billing_installer_preserves_endpoint_implementations():
    checkout_impl = billing.create_checkout_session.__code__
    status_impl = billing.billing_status.__code__
    install_commercial_billing_lifecycle()
    assert billing.create_checkout_session.__code__ is checkout_impl
    assert billing.billing_status.__code__ is status_impl


def test_legacy_product_shell_checkout_is_not_the_portal_authority():
    assert callable(product_shell.billing_checkout)

from inspect import getsource
from types import SimpleNamespace

from app.api.v1 import billing
from app.main import app
from app.services import commercial_control
from app.services.commercial_billing_lifecycle import apply_authoritative_billing_event
from app.services.quota import reserve_quota


class _NoSchemaDB:
    def get_bind(self):
        raise RuntimeError("schema inspection intentionally unavailable")


def _org(**overrides):
    values = {
        "id": "org_test",
        "plan": "free",
        "plan_version": "2026-07",
        "customer_class": "individual_operator",
        "organization_type": None,
        "subscription_status": "inactive",
        "subscription_source": "local",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "stripe_product_id": None,
        "current_period_start": None,
        "current_period_end": None,
        "cancel_at_period_end": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_billing_module_uses_authoritative_subscription_lifecycle():
    assert billing._apply_billing_event is apply_authoritative_billing_event


def test_checkout_completion_does_not_activate_or_upgrade_subscription():
    org = _org()
    billing._apply_billing_event(
        None,
        org,
        "checkout.session.completed",
        {
            "customer": "cus_test",
            "subscription": "sub_test",
            "mode": "subscription",
            "metadata": {"plan": "team", "checkout_mode": "subscription"},
        },
    )
    assert org.plan == "free"
    assert org.subscription_status == "incomplete"
    assert org.stripe_customer_id == "cus_test"
    assert org.stripe_subscription_id == "sub_test"


def test_invoice_success_does_not_independently_activate_subscription():
    org = _org(plan="professional", subscription_status="past_due")
    billing._apply_billing_event(None, org, "invoice.payment_succeeded", {})
    assert org.plan == "professional"
    assert org.subscription_status == "past_due"


def test_one_time_payment_does_not_mutate_saas_plan():
    org = _org()
    billing._apply_billing_event(
        None,
        org,
        "payment_intent.succeeded",
        {"metadata": {"plan": "assurance_audit", "checkout_mode": "payment"}},
    )
    assert org.plan == "free"
    assert org.subscription_status == "inactive"


def test_one_time_offer_metadata_has_no_saas_plan(monkeypatch):
    monkeypatch.setattr(billing.settings, "STRIPE_PRICE_ASSURANCE_AUDIT_FARM", "price_audit")
    config = billing._offer_config("assurance_audit_farm")
    assert config["mode"] == "payment"
    assert config["plan"] is None


def test_inactive_paid_plan_is_free_equivalent_at_runtime():
    org = _org(plan="team", subscription_status="past_due")
    effective = commercial_control.resolve_effective_entitlements(_NoSchemaDB(), org)
    assert effective.plan == "team"
    assert effective.value("intelligence.profile") == "essential"
    assert effective.state("team.invite") == "locked"
    assert effective.state("agents.execute_approval_gated") == "locked"
    assert effective.value("quota.seat") == 1
    assert effective.state("intelligence.ask") == "enabled"


def test_direct_report_routes_have_commercial_dependency_installed():
    expected = {
        "/v1/intelligence/chat/report-pdf",
        "/v1/intelligence/chat/report-email",
    }
    found = {}
    for route in app.routes:
        if getattr(route, "path", None) not in expected:
            continue
        dependencies = {
            getattr(getattr(dep, "dependency", None), "__name__", "")
            for dep in getattr(route, "dependencies", [])
        }
        found[route.path] = dependencies
    assert set(found) == expected
    for dependencies in found.values():
        assert "enforce_report_commercial_boundary" in dependencies


def test_quota_reservation_rechecks_idempotency_after_org_lock():
    source = getsource(reserve_quota)
    lock_position = source.index("with_for_update")
    second_lookup_position = source.rindex("_reservation_for_request")
    assert second_lookup_position > lock_position

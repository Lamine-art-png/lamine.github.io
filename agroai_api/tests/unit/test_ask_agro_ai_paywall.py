from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.ask_agro_ai_paywall import _require_paid_ask
from app.main import app
from app.services.ask_agro_ai_commercial_policy import install_ask_agro_ai_commercial_policy
from app.services.commercial_control import BASE_ENTITLEMENTS, PAID_VARIABLE_COST_FEATURES
from app.services.product_plans import plan_by_id


class FakeDB:
    def __init__(self, org):
        self.org = org

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.org

    def get_bind(self):
        raise RuntimeError("no database metadata in focused unit test")


def org(plan: str, subscription_status: str = "active"):
    return SimpleNamespace(
        id=f"org-{plan}",
        plan=plan,
        subscription_status=subscription_status,
        plan_version=None,
        customer_class=None,
        organization_type=None,
    )


def first_post_endpoint(path: str):
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and "POST" in set(getattr(route, "methods", None) or ())
    ]
    assert routes, f"expected POST route {path}"
    return routes[0].endpoint


def test_free_has_no_ask_agro_ai_or_deep_preview_capacity():
    install_ask_agro_ai_commercial_policy()
    free = BASE_ENTITLEMENTS["free"]
    assert free["intelligence.ask"] == "locked"
    assert free["quota.ai_action.monthly"] == 0
    assert free["quota.deep_investigation.monthly"] == 0
    assert "intelligence.ask" in PAID_VARIABLE_COST_FEATURES


def test_paid_plans_keep_ask_agro_ai_enabled():
    install_ask_agro_ai_commercial_policy()
    for plan in ("professional", "team", "network", "enterprise"):
        assert BASE_ENTITLEMENTS[plan]["intelligence.ask"] == "enabled"


def test_public_plan_catalog_stops_advertising_free_ai_and_starts_at_professional():
    install_ask_agro_ai_commercial_policy()
    free = plan_by_id("free")
    professional = plan_by_id("professional")
    assert "messages" not in free["included_limits"]
    assert "Ask AGRO-AI" in free["locked_features"]
    assert "Deep analysis" in free["locked_features"]
    assert "Ask AGRO-AI" in professional["features"]


def test_free_organization_gets_structured_professional_402():
    with pytest.raises(HTTPException) as exc_info:
        _require_paid_ask(FakeDB(org("free")), "org-free")
    exc = exc_info.value
    assert exc.status_code == 402
    assert exc.detail["code"] == "upgrade_required"
    assert exc.detail["feature"] == "intelligence.ask"
    assert exc.detail["recommended_plan"] == "professional"


def test_active_professional_organization_passes_paid_boundary():
    paid = org("professional", "active")
    assert _require_paid_ask(FakeDB(paid), paid.id) is paid


def test_inactive_professional_organization_fails_closed():
    with pytest.raises(HTTPException) as exc_info:
        _require_paid_ask(FakeDB(org("professional", "canceled")), "org-professional")
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "subscription_inactive"
    assert exc_info.value.detail["feature"] == "intelligence.ask"


def test_authoritative_paid_boundary_is_first_for_every_portal_inference_route():
    for path in (
        "/v1/runtime/intelligence-run",
        "/v1/intelligence/brain/run",
        "/v1/intelligence/brain/run-safe",
        "/v1/intelligence/brain/run-commercial",
        "/v1/intelligence/run",
        "/v1/ai/chat",
    ):
        endpoint = first_post_endpoint(path)
        assert endpoint.__module__ == "app.api.v1.ask_agro_ai_paywall", (
            path,
            endpoint.__module__,
        )

from app.main import app
from app.services.commercial_control import BASE_ENTITLEMENTS
from app.services.live_intelligence import LiveIntelligence


def test_reasoning_profiles_are_distinct():
    engine = LiveIntelligence()
    assert engine.profile("chat_fast", "How is the field?") == "fast"
    assert engine.profile("chat", "Assess evidence and recommend next steps") == "reasoning"
    assert engine.profile("deep_analysis", "Assess evidence and recommend next steps") == "deep"
    assert engine.profile("report_factory", "Create the operating packet") == "report"


def test_commercial_reasoning_route_is_mounted_once():
    routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/v1/intelligence/brain/run-commercial"
        and "POST" in set(getattr(route, "methods", None) or ())
    ]
    assert len(routes) == 1


def test_ai_and_deep_capacity_ladder_is_exact():
    assert [BASE_ENTITLEMENTS[p]["quota.ai_action.monthly"] for p in ("free", "professional", "team", "network", "enterprise")] == [0, 500, 2500, 10000, None]
    assert [BASE_ENTITLEMENTS[p]["quota.deep_investigation.monthly"] for p in ("free", "professional", "team", "network", "enterprise")] == [0, 25, 150, 750, None]

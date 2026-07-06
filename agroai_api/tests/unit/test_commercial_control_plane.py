from datetime import datetime
from types import SimpleNamespace

from app.services.commercial_control import BASE_ENTITLEMENTS, canonical_plan
from app.services.entitlements import serialize_entitlements
from app.services.intelligence_policy import PROFILE_BASE, TASK_ADJUSTMENTS
from app.services.product_plans import ALIASES, plan_by_id
from app.services.quota import current_period


def test_legacy_aliases_preserve_current_main_semantics():
    assert ALIASES == {
        "pilot": "free",
        "assurance_audit": "professional",
        "waterops": "professional",
        "assurance": "team",
        "pro": "professional",
    }
    assert canonical_plan("pilot") == "free"
    assert canonical_plan("assurance_audit") == "professional"
    assert canonical_plan("waterops") == "professional"
    assert canonical_plan("assurance") == "team"
    assert canonical_plan("pro") == "professional"


def test_public_plan_catalog_keeps_five_canonical_plans():
    assert [plan_by_id(code)["id"] for code in ("free", "professional", "team", "network", "enterprise")] == [
        "free",
        "professional",
        "team",
        "network",
        "enterprise",
    ]
    assert plan_by_id("unknown")["id"] == "free"


def test_commercial_intelligence_profiles_are_separate_from_task_profiles():
    assert BASE_ENTITLEMENTS["free"]["intelligence.profile"] == "essential"
    assert BASE_ENTITLEMENTS["professional"]["intelligence.profile"] == "operational"
    assert BASE_ENTITLEMENTS["team"]["intelligence.profile"] == "collaborative"
    assert BASE_ENTITLEMENTS["network"]["intelligence.profile"] == "network"
    assert BASE_ENTITLEMENTS["enterprise"]["intelligence.profile"] == "institutional"
    assert set(TASK_ADJUSTMENTS) == {"fast", "reasoning", "report"}
    assert set(PROFILE_BASE) == {"essential", "operational", "collaborative", "network", "institutional"}


def test_enterprise_capacity_is_contract_configured_not_fake_unlimited():
    enterprise = BASE_ENTITLEMENTS["enterprise"]
    assert enterprise["quota.workspace"] is None
    assert enterprise["quota.seat"] is None
    assert enterprise["quota.ai_action.monthly"] is None
    assert enterprise["quota.active_connector"] is None
    assert enterprise["connectors.custom_api"] == "contract_only"


def test_higher_plans_expand_scope_without_gating_truth_or_security():
    assert BASE_ENTITLEMENTS["free"]["intelligence.ask"] == "enabled"
    assert BASE_ENTITLEMENTS["professional"]["intelligence.deep_analysis"] == "enabled"
    assert BASE_ENTITLEMENTS["team"]["intelligence.shared_memory"] == "enabled"
    assert BASE_ENTITLEMENTS["network"]["intelligence.cross_workspace"] == "enabled"
    assert BASE_ENTITLEMENTS["enterprise"]["intelligence.portfolio_synthesis"] == "enabled"


def test_serialized_entitlements_expose_customer_safe_capabilities_and_quotas():
    free_org = SimpleNamespace(
        plan="free",
        subscription_status="inactive",
        plan_version="2026-07",
        customer_class="individual_operator",
        organization_type="grower",
    )
    payload = serialize_entitlements(free_org)
    assert payload["plan"] == "free"
    assert payload["customer_class"] == "individual_operator"
    assert payload["intelligence_profile"] == "essential"
    assert payload["capabilities"]["intelligence.ask"] == "enabled"
    assert payload["capabilities"]["reports.pdf_export"] == "locked"
    assert payload["quotas"]["workspace"] == 1


def test_serialized_enterprise_plan_stays_enterprise_and_contract_configured():
    org = SimpleNamespace(
        plan="enterprise",
        subscription_status="contracted",
        plan_version="2026-07",
        customer_class="institutional_enterprise",
        organization_type="water_agency",
    )
    payload = serialize_entitlements(org)
    assert payload["plan"] == "enterprise"
    assert payload["plan_name"] == "Enterprise"
    assert payload["intelligence_profile"] == "institutional"
    assert payload["quotas"]["workspace"] is None


def test_quota_period_prefers_active_subscription_window():
    org = SimpleNamespace(
        current_period_start=datetime(2026, 7, 5, 12, 0, 0),
        current_period_end=datetime(2026, 8, 5, 12, 0, 0),
    )
    key, start, end = current_period(org, datetime(2026, 7, 20, 12, 0, 0))
    assert key.startswith("subscription:")
    assert start == org.current_period_start
    assert end == org.current_period_end


def test_quota_period_falls_back_to_calendar_month():
    org = SimpleNamespace(current_period_start=None, current_period_end=None)
    key, start, end = current_period(org, datetime(2026, 7, 20, 12, 0, 0))
    assert key == "calendar:2026-07"
    assert start == datetime(2026, 7, 1, 0, 0, 0)
    assert end == datetime(2026, 8, 1, 0, 0, 0)

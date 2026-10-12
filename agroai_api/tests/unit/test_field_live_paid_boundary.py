"""Protect expensive live Field Intelligence AI while preserving free captures."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.field_intelligence import enforce_paid_live_field_ai
from app.main import app


class _NoSchemaDB:
    def get_bind(self):
        # Focused entitlement tests do not need a real commercial database.
        raise RuntimeError("no database schema in focused test")


def _context(plan: str, subscription_status: str):
    org = SimpleNamespace(
        id="synthetic-org",
        plan=plan,
        subscription_status=subscription_status,
        plan_version=None,
        customer_class=None,
        organization_type=None,
    )
    return SimpleNamespace(organization=org)


@pytest.mark.parametrize(
    "plan,subscription_status,expected_code",
    [
        ("free", "inactive", "upgrade_required"),
        ("professional", "canceled", "subscription_inactive"),
        ("team", "past_due", "subscription_inactive"),
    ],
)
def test_unpaid_organizations_cannot_run_live_field_ai(
    plan, subscription_status, expected_code
):
    with pytest.raises(HTTPException) as exc_info:
        enforce_paid_live_field_ai(ctx=_context(plan, subscription_status), db=_NoSchemaDB())
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == expected_code
    assert exc_info.value.detail["recommended_plan"] == "professional"


@pytest.mark.parametrize("plan", ["professional", "team", "network", "enterprise"])
def test_active_paid_organizations_retain_live_field_ai(plan):
    assert enforce_paid_live_field_ai(ctx=_context(plan, "active"), db=_NoSchemaDB()) is None


def test_both_cost_generating_live_routes_enforce_paid_gate_before_endpoint():
    protected_routes = {
        "/v1/field-intelligence/live-analysis",
        "/v1/field-intelligence/live-transcription",
    }
    discovered = {}
    for route in app.routes:
        if getattr(route, "path", None) in protected_routes and "POST" in (
            getattr(route, "methods", None) or set()
        ):
            discovered[route.path] = {
                getattr(dependency, "dependency", None)
                for dependency in getattr(route, "dependencies", [])
            }
    assert set(discovered) == protected_routes
    assert all(enforce_paid_live_field_ai in dependencies for dependencies in discovered.values())



def test_crop_intelligence_calculators_use_the_existing_paid_tier():
    """Owner audit: the calculators are not free conversion features."""
    from app.api.v1.field_intelligence import enforce_paid_crop_intelligence

    with pytest.raises(HTTPException) as exc_info:
        enforce_paid_crop_intelligence(ctx=_context("free", "inactive"), db=_NoSchemaDB())
    assert exc_info.value.status_code == 402 and exc_info.value.detail["recommended_plan"] == "professional"
    for plan in ("professional", "team", "network", "enterprise"):
        assert enforce_paid_crop_intelligence(ctx=_context(plan, "active"), db=_NoSchemaDB()) is None
    protected = {
        "/v1/field-intelligence/crop-intelligence/harvest-window",
        "/v1/field-intelligence/crop-intelligence/production-estimate",
        "/v1/field-intelligence/crop-intelligence/maturity-stages",
    }
    found = {route.path: {getattr(dep, "dependency", None) for dep in getattr(route, "dependencies", [])}
             for route in app.routes if getattr(route, "path", None) in protected}
    assert set(found) == protected
    assert all(enforce_paid_crop_intelligence in deps for deps in found.values())

from app.api.v1 import connector_upload_commercial
from app.api.v1.connectors import CATALOG
from app.main import app
from app.services.commercial_control import BASE_ENTITLEMENTS
from app.services.commercial_packaging_v2 import (
    EVIDENCE_UPLOAD_LIMITS,
    feature_for_provider,
    required_plan_for_provider,
)


def test_evidence_import_quota_ladder_is_exact():
    assert EVIDENCE_UPLOAD_LIMITS == {
        "free": 15,
        "professional": 500,
        "team": 2500,
        "network": 10000,
        "enterprise": None,
    }
    assert BASE_ENTITLEMENTS["free"]["quota.evidence_upload.monthly"] == 15
    assert BASE_ENTITLEMENTS["professional"]["quota.evidence_upload.monthly"] == 500
    assert BASE_ENTITLEMENTS["team"]["quota.evidence_upload.monthly"] == 2500
    assert BASE_ENTITLEMENTS["network"]["quota.evidence_upload.monthly"] == 10000
    assert BASE_ENTITLEMENTS["enterprise"]["quota.evidence_upload.monthly"] is None


def test_connector_packaging_matches_customer_segments():
    assert required_plan_for_provider("manual_csv") == "free"
    assert required_plan_for_provider("chat_upload") == "free"
    assert required_plan_for_provider("weather") == "professional"
    assert required_plan_for_provider("openet") == "professional"
    assert required_plan_for_provider("wiseconn") == "professional"
    assert required_plan_for_provider("talgil") == "professional"
    assert required_plan_for_provider("custom_api") == "network"
    assert required_plan_for_provider("universal_controller") == "enterprise"
    assert required_plan_for_provider("salesforce") == "enterprise"
    assert required_plan_for_provider("google_earth_engine") == "enterprise"


def test_custom_api_and_bespoke_integrations_are_distinct_capabilities():
    assert feature_for_provider("custom_api") == "connectors.custom_api"
    assert feature_for_provider("universal_controller") == "connectors.custom_integration"
    assert feature_for_provider("salesforce") == "connectors.custom_integration"
    assert BASE_ENTITLEMENTS["professional"]["connectors.custom_api"] == "locked"
    assert BASE_ENTITLEMENTS["team"]["connectors.custom_api"] == "locked"
    assert BASE_ENTITLEMENTS["network"]["connectors.custom_api"] == "enabled"
    assert BASE_ENTITLEMENTS["enterprise"]["connectors.custom_api"] == "enabled"


def test_customer_visible_catalog_uses_packaging_v2_required_plans():
    by_id = {item["id"]: item for item in CATALOG}
    assert by_id["weather"]["required_plan"] == "professional"
    assert by_id["openet"]["required_plan"] == "professional"
    assert by_id["wiseconn"]["required_plan"] == "professional"
    assert by_id["talgil"]["required_plan"] == "professional"
    assert by_id["custom_api"]["required_plan"] == "network"
    assert by_id["salesforce"]["required_plan"] == "enterprise"


def test_exactly_one_live_evidence_upload_route_is_quota_metered():
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v1/evidence/upload"
        and "POST" in set(getattr(route, "methods", None) or ())
    ]
    assert len(routes) == 1
    assert routes[0].endpoint is connector_upload_commercial.upload_commercial_evidence_file

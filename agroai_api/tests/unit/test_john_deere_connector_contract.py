from __future__ import annotations

import urllib.parse

from app.api.v1.connector_launch import CONNECTOR_MANIFESTS, OAUTH_PROVIDERS
from app.api.v1.connectors import catalog_item
from app.services.john_deere_sync import GLOBAL_ROUTE_SPECS, ORG_ROUTE_SPECS, _trusted_api_url
from app.services.oauth_urls import oauth_url
from app.services.provider_sync_jobs import SUPPORTED_PROVIDERS


def test_john_deere_oauth_url_is_customer_authorized_and_excludes_work_plans(monkeypatch):
    monkeypatch.setenv("JOHN_DEERE_OAUTH_CLIENT_ID", "deere-client")
    monkeypatch.setenv(
        "JOHN_DEERE_OAUTH_SCOPES",
        "ag1 ag2 ag3 eq1 eq2 org1 org2 offline_access",
    )

    url, error = oauth_url(
        "john_deere",
        "signed-state",
        "https://api.agroai-pilot.com/v1/connectors/oauth/callback",
    )

    assert error is None
    assert url is not None
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    assert parsed.netloc == "signin.johndeere.com"
    assert query["client_id"] == ["deere-client"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["signed-state"]
    assert query["redirect_uri"] == ["https://api.agroai-pilot.com/v1/connectors/oauth/callback"]
    assert "offline_access" in query["scope"][0].split()
    assert not any("work" in scope.lower() for scope in query["scope"][0].split())


def test_john_deere_is_first_class_oauth_catalog_and_sync_provider():
    assert "john_deere" in OAUTH_PROVIDERS
    assert "john_deere" in SUPPORTED_PROVIDERS
    catalog = catalog_item("john_deere")
    assert catalog is not None
    assert catalog["connection_methods"] == ["oauth"]
    assert catalog["required_plan"] == "pro"
    manifest = CONNECTOR_MANIFESTS["john_deere"]
    assert manifest["auth_pattern"] == "oauth"
    assert manifest["required_env"] == [
        "JOHN_DEERE_OAUTH_CLIENT_ID",
        "JOHN_DEERE_OAUTH_CLIENT_SECRET",
    ]
    assert "field operations" in manifest["data_objects"]


def test_phase_one_deere_sync_never_calls_work_plans():
    routes = [route for route, _record_type in (*ORG_ROUTE_SPECS, *GLOBAL_ROUTE_SPECS)]
    assert routes
    assert all("workplan" not in route.lower() for route in routes)
    assert "fieldOperations" in routes
    assert "fields" in routes
    assert "boundaries" in routes
    assert "equipment" in routes


def test_deere_pagination_cannot_exfiltrate_bearer_token(monkeypatch):
    monkeypatch.setenv("JOHN_DEERE_API_BASE_URL", "https://api.deere.com/platform")
    assert _trusted_api_url("/platform/organizations?page=2") == "https://api.deere.com/platform/organizations?page=2"
    assert _trusted_api_url("https://api.deere.com/platform/organizations?page=2") == "https://api.deere.com/platform/organizations?page=2"
    assert _trusted_api_url("https://evil.example/steal") is None
    assert _trusted_api_url("http://api.deere.com/platform/organizations?page=2") is None
    assert _trusted_api_url("https://api.deere.com/other-root") is None

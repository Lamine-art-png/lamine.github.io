"""Connectors that cannot deliver data are never presented or launched as available."""
import pytest

from app.api.v1 import connectors
from app.services.connector_availability import COMING_SOON_PROVIDERS


def test_catalog_marks_non_ingesting_providers_coming_soon(monkeypatch):
    for name in ("BOX_OAUTH_CLIENT_ID", "SLACK_OAUTH_CLIENT_ID", "DROPBOX_OAUTH_CLIENT_ID"):
        monkeypatch.setenv(name, "configured-client")
    catalog = {item["id"]: item for item in connectors.get_catalog()["connectors"]}
    for provider in COMING_SOON_PROVIDERS:
        assert catalog[provider]["status"] == "coming_soon", provider
    assert catalog["google_drive"]["status"] != "coming_soon"
    assert catalog["outlook"]["status"] != "coming_soon"


@pytest.mark.parametrize("path", ["/v1/connectors/launch/start", "/v1/connectors/oauth/start"])
@pytest.mark.parametrize("provider", sorted(COMING_SOON_PROVIDERS))
def test_launch_refuses_coming_soon_providers(client, path, provider):
    from app.core.security import require_current_tenant_id
    from app.main import app

    app.dependency_overrides[require_current_tenant_id] = lambda: "tenant-a"
    try:
        response = client.post(path, json={"provider": provider, "workspace_id": "ws-1", "metadata": {}})
    finally:
        app.dependency_overrides.pop(require_current_tenant_id, None)
    if path.endswith("/oauth/start") and provider == "google_earth_engine":
        assert response.status_code == 422  # not an OAuth provider at all
        return
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "connector_coming_soon"

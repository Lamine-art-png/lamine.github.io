from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _StubWiseConnAdapter:
    async def check_auth(self):
        return True

    async def list_farms(self):
        return [{"id": "42", "name": "North Farm", "provider": "wiseconn"}]

    async def list_zones(self, farm_id: str):
        return [
            {"id": "1001", "name": "Block A", "provider": "wiseconn"},
            {"id": "1002", "name": "Block B", "provider": "wiseconn"},
        ]


class _StubTalgilLiveAdapter:
    configured = True

    async def check_auth(self):
        return True

    async def list_targets(self):
        return [{"id": "6115", "name": "Talgil Controller", "provider": "talgil"}]

    async def list_zones(self, farm_id: str):
        return [
            {"id": "S-1", "name": "Pressure Sensor", "provider": "talgil", "controller_id": farm_id},
            {"id": "S-2", "name": "Flow Sensor", "provider": "talgil", "controller_id": farm_id},
        ]


class _StubTalgilReadyAdapter:
    configured = False

    async def check_auth(self):
        return False


class _StubTalgilConfiguredButOfflineAdapter:
    configured = True

    async def check_auth(self):
        return False


def test_controller_environments_endpoint_live_talgil(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnAdapter())
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilLiveAdapter())

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    assert payload["totals"]["farms"] == 2
    assert payload["totals"]["zones"] == 4

    wiseconn = next(item for item in payload["environments"] if item["source"] == "wiseconn")
    talgil = next(item for item in payload["environments"] if item["source"] == "talgil")

    assert wiseconn["status"] == "live"
    assert wiseconn["sources"]["wiseconn"] == 2
    assert talgil["status"] == "live"
    assert talgil["live"] is True
    assert talgil["farms"] == 1
    assert talgil["zones"] == 2


def test_controller_environments_endpoint_talgil_integration_ready(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnAdapter())
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilReadyAdapter())

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    talgil = next(item for item in payload["environments"] if item["source"] == "talgil")
    wiseconn = next(item for item in payload["environments"] if item["source"] == "wiseconn")
    assert talgil["status"] == "integration_ready"
    assert talgil["live"] is False
    assert wiseconn["status"] == "live"


def test_controller_environments_endpoint_talgil_configured_not_live(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnAdapter())
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilConfiguredButOfflineAdapter())

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    talgil = next(item for item in payload["environments"] if item["source"] == "talgil")
    assert talgil["status"] == "configured"
    assert talgil["configured"] is True
    assert talgil["live"] is False
    assert "auth/read checks failed" in talgil["notes"]

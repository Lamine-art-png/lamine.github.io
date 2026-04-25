from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _StubTalgilAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = True

    async def check_auth(self):
        return True

    async def list_targets(self):
        return [{"id": "6115", "name": "Controller 6115", "provider": "talgil"}]

    async def get_target_image(self, controller_id: str):
        if controller_id != "6115":
            return {}
        return {"ID": 6115, "Name": "Controller 6115", "Sensors": [{"UID": "S-1", "Value": 12.3}]}

    async def list_farms(self):
        return await self.list_targets()

    async def list_zones(self, farm_id: str):
        return [{"id": "S-1", "name": "Pressure", "provider": "talgil", "controller_id": farm_id}]


class _StubTalgilMissingCredsAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = False

    async def check_auth(self):
        return False

    async def list_targets(self):
        return []

    async def list_zones(self, farm_id: str):
        return []

    async def get_target_image(self, controller_id: str):
        return {}


def test_talgil_runtime_routes(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilAdapter())

    client = TestClient(app)

    auth_resp = client.get("/v1/talgil/auth")
    assert auth_resp.status_code == 200
    assert auth_resp.json()["authenticated"] is True

    targets_resp = client.get("/v1/talgil/targets")
    assert targets_resp.status_code == 200
    assert len(targets_resp.json()) == 1

    image_resp = client.get("/v1/talgil/targets/6115")
    assert image_resp.status_code == 200
    assert image_resp.json()["ID"] == 6115

    zones_resp = client.get("/v1/talgil/farms/6115/zones")
    assert zones_resp.status_code == 200
    assert zones_resp.json()[0]["provider"] == "talgil"

    status_resp = client.get("/v1/talgil/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "live"
    assert status_resp.json()["targets"] == 1
    assert status_resp.json()["sensors"] == 1

    sensors_resp = client.get("/v1/talgil/sensors")
    assert sensors_resp.status_code == 200
    assert sensors_resp.json()[0]["provider"] == "talgil"


def test_talgil_target_not_found(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilAdapter())

    client = TestClient(app)
    image_resp = client.get("/v1/talgil/targets/9999")
    assert image_resp.status_code == 404


def test_talgil_status_missing_credentials(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilMissingCredsAdapter())

    client = TestClient(app)
    status_resp = client.get("/v1/talgil/status")
    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["status"] == "integration_ready"
    assert payload["configured"] is False
    assert payload["live"] is False

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


def test_controller_environments_endpoint(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnAdapter())

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    assert payload["totals"]["farms"] == 1
    assert payload["totals"]["zones"] == 2

    wiseconn = next(item for item in payload["environments"] if item["source"] == "wiseconn")
    talgil = next(item for item in payload["environments"] if item["source"] == "talgil")

    assert wiseconn["status"] == "live"
    assert wiseconn["sources"]["wiseconn"] == 2
    assert talgil["status"] == "integration_ready"
    assert talgil["live"] is False

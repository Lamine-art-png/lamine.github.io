from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _StubWiseConnAdapter:
    def __init__(self):
        self.check_auth_calls = 0
        self.list_farms_calls = 0
        self.list_zones_calls = 0

    async def check_auth(self):
        self.check_auth_calls += 1
        return True

    async def list_farms(self):
        self.list_farms_calls += 1
        return [{"id": "42", "name": "North Farm", "provider": "wiseconn"}]

    async def list_zones(self, farm_id: str):
        self.list_zones_calls += 1
        return [
            {"id": "1001", "name": "Block A", "provider": "wiseconn"},
            {"id": "1002", "name": "Block B", "provider": "wiseconn"},
        ]


class _StubTalgilStatusAdapter:
    def __init__(self, *, configured, status, live, targets=0):
        self.configured = configured
        self.status_calls = 0
        self.list_targets_calls = 0
        self.list_zones_calls = 0
        self._status = SimpleNamespace(
            status=status,
            configured=configured,
            live=live,
            targets=targets,
            notes=(
                "Live runtime checks succeeded against Talgil read endpoints."
                if live
                else (
                    "TALGIL_API_KEY is present but runtime auth/read checks did not succeed."
                    if configured
                    else "TALGIL_API_KEY is not configured in this runtime."
                )
            ),
        )

    async def get_runtime_status(self, *, use_cache=True):
        self.status_calls += 1
        return self._status

    async def list_targets(self):
        self.list_targets_calls += 1
        return [{"id": "6115"}]

    async def list_zones(self, farm_id: str):
        self.list_zones_calls += 1
        return [{"id": "S-1"}]



def test_controller_environments_endpoint_live_talgil_uses_cached_status(monkeypatch):
    wiseconn = _StubWiseConnAdapter()
    talgil = _StubTalgilStatusAdapter(configured=True, status="live", live=True, targets=1)

    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: wiseconn)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: talgil)

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    assert payload["totals"]["farms"] == 2
    assert payload["totals"]["zones"] == 2

    wiseconn_env = next(item for item in payload["environments"] if item["source"] == "wiseconn")
    talgil_env = next(item for item in payload["environments"] if item["source"] == "talgil")

    assert wiseconn_env["status"] == "live"
    assert wiseconn_env["sources"]["wiseconn"] == 2
    assert talgil_env["status"] == "live"
    assert talgil_env["live"] is True
    assert talgil_env["farms"] == 1
    assert talgil_env["zones"] == 0

    assert talgil.status_calls == 1
    assert talgil.list_targets_calls == 0
    assert talgil.list_zones_calls == 0


def test_controller_environments_endpoint_talgil_integration_ready(monkeypatch):
    wiseconn = _StubWiseConnAdapter()
    talgil = _StubTalgilStatusAdapter(configured=False, status="integration_ready", live=False)

    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: wiseconn)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: talgil)

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    talgil_env = next(item for item in payload["environments"] if item["source"] == "talgil")
    wiseconn_env = next(item for item in payload["environments"] if item["source"] == "wiseconn")
    assert talgil_env["status"] == "integration_ready"
    assert talgil_env["live"] is False
    assert wiseconn_env["status"] == "live"


def test_controller_environments_endpoint_talgil_configured_not_live(monkeypatch):
    wiseconn = _StubWiseConnAdapter()
    talgil = _StubTalgilStatusAdapter(configured=True, status="configured", live=False)

    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: wiseconn)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: talgil)

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    payload = response.json()
    talgil_env = next(item for item in payload["environments"] if item["source"] == "talgil")
    assert talgil_env["status"] == "configured"
    assert talgil_env["configured"] is True
    assert talgil_env["live"] is False
    assert "did not succeed" in talgil_env["notes"]


def test_wiseconn_path_unchanged(monkeypatch):
    wiseconn = _StubWiseConnAdapter()
    talgil = _StubTalgilStatusAdapter(configured=True, status="configured", live=False)

    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: wiseconn)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: talgil)

    client = TestClient(app)
    response = client.get("/v1/controllers/environments")
    assert response.status_code == 200

    assert wiseconn.check_auth_calls == 1
    assert wiseconn.list_farms_calls == 1
    assert wiseconn.list_zones_calls == 1

from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _Diag:
    def __init__(self, error_type=None, message=None, status_code=None, preview=None, shape=None):
        self.error_type = error_type
        self.error_message_sanitized = message
        self.upstream_status_code = status_code
        self.upstream_response_preview_sanitized = preview
        self.response_shape = shape


class _StubTalgilAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = True

    def __init__(self):
        self.last_diagnostic = _Diag(shape="list")

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

    def __init__(self):
        self.last_diagnostic = _Diag("MissingApiKey", "TALGIL_API_KEY is not configured in this runtime.")

    async def check_auth(self):
        return False

    async def list_targets(self):
        return []

    async def list_zones(self, farm_id: str):
        return []

    async def get_target_image(self, controller_id: str):
        return {}


class _StubTalgilConfiguredFailureAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = True

    def __init__(self, error_type, message, status_code=None, preview=None, shape=None):
        self.last_diagnostic = _Diag(error_type, message, status_code, preview, shape)

    async def check_auth(self):
        return False

    async def list_targets(self):
        return []

    async def list_zones(self, farm_id: str):
        return []


class _StubTalgilSensorsRaisesAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = True

    def __init__(self):
        self.last_diagnostic = _Diag("TalgilAuthError", "Talgil auth failed (GET /mytargets)", 401, "denied", "text")

    async def check_auth(self):
        raise RuntimeError("boom")


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
    assert status_resp.json()["auth_header_used"] == "TLG-API-Key"
    assert status_resp.json()["auth_check_path"] == "/mytargets"

    sensors_resp = client.get("/v1/talgil/sensors")
    assert sensors_resp.status_code == 200
    assert sensors_resp.json()["ok"] is True
    assert sensors_resp.json()["sensors"][0]["provider"] == "talgil"


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


def test_talgil_status_diagnostics_wrong_key_401(monkeypatch):
    monkeypatch.setattr(
        AdapterRegistry,
        "get_talgil",
        lambda: _StubTalgilConfiguredFailureAdapter(
            "TalgilAuthError",
            "Talgil auth failed (GET /mytargets)",
            status_code=401,
            preview="Unauthorized",
            shape="text",
        ),
    )
    client = TestClient(app)
    payload = client.get("/v1/talgil/status").json()
    assert payload["status"] == "configured"
    assert payload["last_error_type"] == "TalgilAuthError"
    assert payload["upstream_status_code"] == 401
    assert payload["response_shape"] == "text"


def test_talgil_status_diagnostics_404(monkeypatch):
    monkeypatch.setattr(
        AdapterRegistry,
        "get_talgil",
        lambda: _StubTalgilConfiguredFailureAdapter(
            "TalgilNotFound",
            "Talgil endpoint not found (GET /mytargets)",
            status_code=404,
            preview="Not Found",
            shape="text",
        ),
    )
    client = TestClient(app)
    payload = client.get("/v1/talgil/status").json()
    assert payload["last_error_type"] == "TalgilNotFound"
    assert payload["upstream_status_code"] == 404


def test_talgil_status_diagnostics_non_json_response(monkeypatch):
    monkeypatch.setattr(
        AdapterRegistry,
        "get_talgil",
        lambda: _StubTalgilConfiguredFailureAdapter(
            "TalgilResponseError",
            "Talgil returned invalid JSON (GET /mytargets)",
            status_code=200,
            preview="<html>bad gateway</html>",
            shape="invalid_json",
        ),
    )
    client = TestClient(app)
    payload = client.get("/v1/talgil/status").json()
    assert payload["last_error_type"] == "TalgilResponseError"
    assert payload["response_shape"] == "invalid_json"


def test_talgil_status_diagnostics_empty_body(monkeypatch):
    monkeypatch.setattr(
        AdapterRegistry,
        "get_talgil",
        lambda: _StubTalgilConfiguredFailureAdapter(
            "TalgilResponseEmpty",
            "Talgil returned empty payload",
            status_code=200,
            preview="",
            shape="empty",
        ),
    )
    client = TestClient(app)
    payload = client.get("/v1/talgil/status").json()
    assert payload["response_shape"] == "empty"


def test_talgil_sensors_failure_returns_json_not_500(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilSensorsRaisesAdapter())
    client = TestClient(app)
    response = client.get("/v1/talgil/sensors")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "configured"
    assert payload["live"] is False
    assert payload["sensors"] == []
    assert payload["error_type"] == "TalgilAuthError"
    assert payload["upstream_status_code"] == 401

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _Diag:
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    def __init__(self, error_type=None, message=None, status_code=None, preview=None, shape=None, retry_after=None):

    def __init__(self, error_type=None, message=None, status_code=None, preview=None, shape=None):
 main
        self.error_type = error_type
        self.error_message_sanitized = message
        self.upstream_status_code = status_code
        self.upstream_response_preview_sanitized = preview
        self.response_shape = shape
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
        self.retry_after_seconds = retry_after


class _StatusStubAdapter:
    api_url = "https://dev.talgil.com/api"

    def __init__(self, *, configured, status, live, targets, diagnostic=None):
        self.configured = configured
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
        self.last_diagnostic = diagnostic or _Diag(shape="list")
        self.list_zones_calls = 0

    async def get_runtime_status(self, *, use_cache=True):
        return self._status



class _StubTalgilAdapter:
    api_url = "https://external.talgil.com/v1"
    configured = True

    def __init__(self):
        self.last_diagnostic = _Diag(shape="list")

    async def check_auth(self):
        return True
 main

    async def list_targets(self):
        return [{"id": "6115", "name": "Controller 6115", "provider": "talgil"}]

    async def get_target_image(self, controller_id: str):
        if controller_id != "6115":
            return {}
        return {"ID": 6115, "Name": "Controller 6115", "Sensors": [{"UID": "S-1", "Value": 12.3}]}

    async def list_farms(self):
        return await self.list_targets()

    async def list_zones(self, farm_id: str):
        self.list_zones_calls += 1
        return [{"id": "S-1", "name": "Pressure", "provider": "talgil", "controller_id": farm_id}]


 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb

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


 main
def test_talgil_runtime_routes(monkeypatch):
    adapter = _StatusStubAdapter(configured=True, status="live", live=True, targets=1)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)

    auth_resp = client.get("/v1/talgil/auth")
    assert auth_resp.status_code == 200
    assert auth_resp.json()["authenticated"] is True

    status_resp = client.get("/v1/talgil/status")
    assert status_resp.status_code == 200
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    payload = status_resp.json()
    assert payload["status"] == "live"
    assert payload["targets"] == 1
    assert payload["sensors"] == 0
    assert payload["auth_header_used"] == "TLG-API-Key"
    assert payload["auth_check_path"] == "/mytargets"

    assert status_resp.json()["status"] == "live"
    assert status_resp.json()["targets"] == 1
    assert status_resp.json()["sensors"] == 1
    assert status_resp.json()["auth_header_used"] == "TLG-API-Key"
    assert status_resp.json()["auth_check_path"] == "/mytargets"
 main

    sensors_resp = client.get("/v1/talgil/sensors")
    assert sensors_resp.status_code == 200
    assert sensors_resp.json()["ok"] is True
    assert sensors_resp.json()["sensors"][0]["provider"] == "talgil"


def test_talgil_target_not_found(monkeypatch):
    adapter = _StatusStubAdapter(configured=True, status="live", live=True, targets=1)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)
    image_resp = client.get("/v1/talgil/targets/9999")
    assert image_resp.status_code == 404


def test_talgil_status_missing_credentials(monkeypatch):
    adapter = _StatusStubAdapter(
        configured=False,
        status="integration_ready",
        live=False,
        targets=0,
        diagnostic=_Diag("MissingApiKey", "TALGIL_API_KEY is not configured in this runtime."),
    )
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)
    status_resp = client.get("/v1/talgil/status")
    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["status"] == "integration_ready"
    assert payload["configured"] is False
    assert payload["live"] is False


 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
def test_talgil_status_diagnostics_429_retry_after(monkeypatch):
    adapter = _StatusStubAdapter(
        configured=True,
        status="configured",
        live=False,
        targets=0,
        diagnostic=_Diag(
            "TalgilRateLimitError",
            "Talgil upstream rate limit reached",
            status_code=429,
            preview="Too Many Requests",
            shape="text",
            retry_after=120,
        ),
    )
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)
    payload = client.get("/v1/talgil/status").json()
    assert payload["status"] == "configured"
    assert payload["upstream_status_code"] == 429
    assert payload["retry_after_seconds"] == 120


def test_talgil_sensors_429_returns_rate_limited(monkeypatch):
    adapter = _StatusStubAdapter(
        configured=True,
        status="configured",
        live=False,
        targets=0,
        diagnostic=_Diag(
            "TalgilRateLimitError",
            "Talgil upstream rate limit reached",
            status_code=429,
            retry_after=45,
        ),
    )
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)


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
 main
    client = TestClient(app)
    response = client.get("/v1/talgil/sensors")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "configured"
    assert payload["live"] is False
    assert payload["sensors"] == []
 codex/fix-talgil-diagnostics-and-sensor-error-handling-lvrhbb
    assert payload["error_type"] == "rate_limited"
    assert payload["upstream_status_code"] == 429
    assert payload["retry_after_seconds"] == 45


def test_talgil_status_does_not_call_sensors(monkeypatch):
    adapter = _StatusStubAdapter(configured=True, status="live", live=True, targets=1)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)
    response = client.get("/v1/talgil/status")
    assert response.status_code == 200
    assert adapter.list_zones_calls == 0

    assert payload["error_type"] == "TalgilAuthError"
    assert payload["upstream_status_code"] == 401
 main

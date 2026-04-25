from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app


class _Diag:
    def __init__(self, error_type=None, message=None, status_code=None, preview=None, shape=None, retry_after=None):
        self.error_type = error_type
        self.error_message_sanitized = message
        self.upstream_status_code = status_code
        self.upstream_response_preview_sanitized = preview
        self.response_shape = shape
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


def test_talgil_runtime_routes(monkeypatch):
    adapter = _StatusStubAdapter(configured=True, status="live", live=True, targets=1)
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: adapter)

    client = TestClient(app)

    auth_resp = client.get("/v1/talgil/auth")
    assert auth_resp.status_code == 200
    assert auth_resp.json()["authenticated"] is True

    status_resp = client.get("/v1/talgil/status")
    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["status"] == "live"
    assert payload["targets"] == 1
    assert payload["sensors"] == 0
    assert payload["auth_header_used"] == "TLG-API-Key"
    assert payload["auth_check_path"] == "/mytargets"

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

    client = TestClient(app)
    response = client.get("/v1/talgil/sensors")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "configured"
    assert payload["live"] is False
    assert payload["sensors"] == []
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

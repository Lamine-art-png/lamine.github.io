from fastapi.testclient import TestClient

from app.adapters.registry import AdapterRegistry
from app.main import app
from app.services.live_field_context import LiveFieldContextAssembler


class _StubWiseConnLiveAdapter:
    async def list_farms(self):
        return [{"id": 10, "name": "North"}]

    async def list_zones(self, farm_id: str):
        return [{"id": "z-1", "enabled": True, "name": "Block Z1"}]

    async def list_measures(self, zone_id: str):
        return [{"id": "m-1"}]

    async def get_last_data(self, measure_id: str):
        return {"value": 23.4}

    async def list_irrigations(self, zone_id: str, start_time=None, end_time=None):
        return [{"id": "i-1"}, {"id": "i-2"}]


class _StubWiseConnMissingTelemetryAdapter(_StubWiseConnLiveAdapter):
    async def list_measures(self, zone_id: str):
        raise RuntimeError("telemetry offline")


class _StubTalgilLiveAdapter:
    async def list_targets(self):
        return [{"id": "6115", "online": True, "name": "T-6115"}]

    async def list_zones(self, farm_id: str):
        return [{"id": "S-1", "value": 19.5}]


class _StubTalgilEmptyAdapter:
    async def list_targets(self):
        return []



def test_wiseconn_live_context_assembly(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnLiveAdapter())
    assembler = LiveFieldContextAssembler()
    result = __import__("asyncio").run(assembler.assemble_wiseconn_zone("z-1"))
    ctx = result["context"]
    assert ctx.source == "wiseconn"
    assert ctx.source_entity_id == "z-1"
    assert ctx.sensor_context.moisture_percent == 23.4
    assert ctx.recent_irrigation_context.events_last_7_days == 2


def test_wiseconn_missing_telemetry_graceful_degradation(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnMissingTelemetryAdapter())
    assembler = LiveFieldContextAssembler()
    result = __import__("asyncio").run(assembler.assemble_wiseconn_zone("z-1"))
    assert "wiseconn_telemetry_unavailable" in result["warnings"]
    assert result["context"].sensor_context.moisture_percent is None


def test_talgil_live_context_assembly(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilLiveAdapter())
    assembler = LiveFieldContextAssembler()
    result = __import__("asyncio").run(assembler.assemble_talgil_target("6115"))
    ctx = result["context"]
    assert ctx.source == "talgil"
    assert ctx.source_entity_id == "6115"
    assert ctx.sensor_context.moisture_percent == 19.5


def test_talgil_empty_target_graceful_behavior(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilEmptyAdapter())
    client = TestClient(app)
    response = client.get("/v1/intelligence/live-context/talgil/9999")
    assert response.status_code == 404


def test_live_recommendation_with_manual_overrides(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnLiveAdapter())
    client = TestClient(app)
    response = client.post(
        "/v1/intelligence/recommend/live",
        json={
            "source": "wiseconn",
            "entity_id": "z-1",
            "crop_type": "grapes",
            "soil_type": "loam",
            "weather_context": {"eto_mm": 5.2, "precipitation_forecast_mm": 0.0},
            "field_observations": ["dry surface"],
            "language": "en",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_trace"]["context_origin"] in {"mixed", "live"}
    assert "crop_type" in payload["source_trace"]["manual_overrides_used"]


def test_source_trace_populated_correctly(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_talgil", lambda: _StubTalgilLiveAdapter())
    client = TestClient(app)
    response = client.post(
        "/v1/intelligence/recommend/live/talgil/6115",
        json={"source": "talgil", "entity_id": "6115", "language": "en"},
    )
    assert response.status_code == 200
    trace = response.json()["source_trace"]
    assert trace["source"] == "talgil"
    assert "live_inputs_used" in trace
    assert "controller_provider" in trace


def test_no_fabricated_telemetry(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnMissingTelemetryAdapter())
    client = TestClient(app)
    response = client.get("/v1/intelligence/live-context/wiseconn/z-1")
    assert response.status_code == 200
    context = response.json()["normalized_context"]
    assert context["sensor_context"]["moisture_percent"] is None


def test_live_recommendation_partial_data_still_works(monkeypatch):
    monkeypatch.setattr(AdapterRegistry, "get_wiseconn", lambda: _StubWiseConnMissingTelemetryAdapter())
    client = TestClient(app)
    response = client.post(
        "/v1/intelligence/recommend/live/wiseconn/z-1",
        json={"source": "wiseconn", "entity_id": "z-1", "language": "en"},
    )
    assert response.status_code == 200
    assert response.json()["action"] in {"inspect", "wait", "insufficient_data", "irrigate"}


def test_existing_manual_recommendation_still_works():
    client = TestClient(app)
    response = client.post(
        "/v1/intelligence/recommend",
        json={
            "field_context": {
                "field_id": "manual-1",
                "crop_type": "grapes",
                "soil_type": "loam",
                "weather_context": {"eto_mm": 4.1, "precipitation_forecast_mm": 0.0},
            },
            "language": "en",
        },
    )
    assert response.status_code == 200

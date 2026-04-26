from fastapi.testclient import TestClient

from app.main import app
from app.services.intelligence_engine import CanonicalFieldContext, IntelligenceEngineV1, RecommendationRequest


def _base_field(**overrides):
    payload = {
        "field_id": "field-1",
        "farm_id": "farm-1",
        "source": "wiseconn",
        "source_entity_id": "zone-1",
        "crop_type": "grape",
        "irrigation_method": "drip",
        "soil_type": "loam",
        "area": 12.0,
        "location": {"region": "Napa"},
        "weather_context": {"eto_mm": 5.6, "precipitation_forecast_mm": 0.4, "temperature_c": 31},
        "sensor_context": {"moisture_percent": 22.5, "flow_m3h": 3.2},
        "controller_context": {"provider": "wiseconn", "online": True},
        "recent_irrigation_context": {"last_depth_mm": 4.0, "events_last_7_days": 3},
        "field_observations": ["Mild afternoon leaf curl yesterday"],
        "confidence_inputs": ["wiseconn_sensor", "forecast"],
    }
    payload.update(overrides)
    return payload


def test_data_quality_full_connected_wiseconn_like():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    quality = engine.evaluate_data_quality(field)
    assert quality.data_quality_label == "full_telemetry"
    assert quality.data_quality_score >= 80


def test_data_quality_talgil_like_source_context():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field(source="talgil", source_entity_id="target-6115"))
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.source_trace["source"] == "talgil"
    assert rec.source_trace["telemetry_used"] is True


def test_no_hardware_field_gets_practical_guidance():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(
        **_base_field(
            source="manual",
            sensor_context={},
            controller_context={},
            weather_context={"eto_mm": 4.8, "precipitation_forecast_mm": 0.0},
            field_observations=["Top soil is dry at 10cm"],
        )
    )
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.action in {"inspect", "irrigate", "wait"}
    assert rec.confidence_label in {"low", "moderate"}


def test_partial_data_field():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(
        **_base_field(sensor_context={}, weather_context={"eto_mm": 5.0, "precipitation_forecast_mm": 0.2})
    )
    quality = engine.evaluate_data_quality(field)
    assert quality.data_quality_label in {"partial_telemetry", "manual_only"}


def test_missing_soil_type_is_declared():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field(soil_type=None))
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert "soil_type" in rec.missing_data
    assert "soil_uncertainty" in rec.risk_flags


def test_missing_crop_type_is_declared():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field(crop_type=None))
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert "crop_type" in rec.missing_data
    assert "crop_demand_unknown" in rec.risk_flags


def test_multilingual_fallback():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    rec = engine.recommend(RecommendationRequest(field_context=field, language="fr"))
    assert rec.language_status.startswith("fallback_to_en")
    assert "en" in rec.human_readable_explanation


def test_low_confidence_recommendation():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(
        field_id="field-low",
        source="manual",
        weather_context={},
        sensor_context={},
        controller_context={},
        recent_irrigation_context={},
    )
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.confidence_label == "low"
    assert rec.action in {"insufficient_data", "inspect"}


def test_high_confidence_recommendation():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.confidence_score >= 70


def test_verification_plan_generation():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.verification_required is True
    assert rec.verification_plan.warning_trigger
    assert rec.execution_task.confirmation_needed is True


def test_no_fabricated_precision_when_weak_data():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(field_id="weak-1", source="manual")
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.recommended_depth_mm is None
    assert rec.recommended_duration_minutes is None


def test_intelligence_routes_endpoints():
    client = TestClient(app)
    normalize_resp = client.post("/v1/intelligence/field-context/normalize", json=_base_field())
    assert normalize_resp.status_code == 200
    quality_resp = client.post("/v1/intelligence/data-quality", json=_base_field())
    assert quality_resp.status_code == 200
    assert "data_quality_score" in quality_resp.json()

    recommend_resp = client.post(
        "/v1/intelligence/recommend",
        json={"field_context": _base_field(), "language": "es", "time_horizon": "today"},
    )
    assert recommend_resp.status_code == 200
    assert "verification_plan" in recommend_resp.json()

    schema_resp = client.get("/v1/intelligence/schema")
    assert schema_resp.status_code == 200
    assert "recommendation_response_schema" in schema_resp.json()

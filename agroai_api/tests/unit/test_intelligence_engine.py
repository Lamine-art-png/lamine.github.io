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


def test_alias_weather_fields_are_normalized():
    engine = IntelligenceEngineV1()
    result = engine.normalize_field_context(
        {
            "field_id": "f1",
            "rain_forecast_mm": 1.2,
            "evapotranspiration_mm": 4.9,
        }
    )
    assert result.normalized_context.weather_context.precipitation_forecast_mm == 1.2
    assert result.normalized_context.weather_context.eto_mm == 4.9


def test_alias_last_irrigation_days_ago_is_converted():
    engine = IntelligenceEngineV1()
    result = engine.normalize_field_context(
        {
            "field_id": "f1",
            "last_irrigation_days_ago": 2,
        }
    )
    assert result.normalized_context.recent_irrigation_context.last_irrigation_at is not None
    assert "last_irrigation_days_ago" in result.aliases_applied


def test_country_and_state_are_handled_cleanly():
    engine = IntelligenceEngineV1()
    result = engine.normalize_field_context(
        {
            "field_id": "f1",
            "country": "Chile",
            "state": "Maule",
            "county": "Talca",
            "latitude": -35.4,
            "longitude": -71.6,
        }
    )
    location = result.normalized_context.location
    assert location.country == "Chile"
    assert location.region == "Maule"
    assert location.county == "Talca"
    assert location.lat == -35.4
    assert location.lon == -71.6


def test_unknown_fields_reported_but_no_crash():
    engine = IntelligenceEngineV1()
    result = engine.normalize_field_context({"field_id": "f1", "banana_mode": "on"})
    assert "banana_mode" in result.ignored_fields


def test_canonical_schema_still_works():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    rec = engine.recommend(RecommendationRequest(field_context=field))
    assert rec.recommendation_id.startswith("rec_")


def test_recommendation_with_alias_weather_no_false_missing_context():
    client = TestClient(app)
    resp = client.post(
        "/v1/intelligence/recommend",
        json={
            "field_context": {
                "field_id": "manual-grapes-1",
                "crop_type": "grapes",
                "soil_type": "loam",
                "area": 5,
                "rain_forecast_mm": 0.0,
                "evapotranspiration_mm": 5.2,
                "last_irrigation_days_ago": 2,
                "state": "Mendoza",
                "country": "Argentina",
            },
            "language": "en",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "weather_context" not in payload["missing_data"]


def test_normalize_endpoint_returns_debug_fields():
    client = TestClient(app)
    resp = client.post(
        "/v1/intelligence/field-context/normalize",
        json={
            "field_id": "f1",
            "rainfall_forecast_mm": 3.1,
            "et0_mm": 4.4,
            "moisture_pct": 21,
            "flow_rate": 2.2,
            "strange_key": "x",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "normalized_context" in payload
    assert "aliases_applied" in payload
    assert "ignored_fields" in payload
    assert "warnings" in payload
    assert "strange_key" in payload["ignored_fields"]


def test_data_quality_full_connected_wiseconn_like():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(**_base_field())
    quality = engine.evaluate_data_quality(field)
    assert quality.data_quality_label == "full_telemetry"
    assert quality.data_quality_score >= 80


def test_compatibility_endpoint_rejects_client_self_attested_validation_labels():
    engine = IntelligenceEngineV1()
    field = CanonicalFieldContext(
        field_id="field-1",
        crop_type="almonds",
        irrigation_method="drip",
        area=2.0,
        crop_coefficient=0.8,
        effective_rainfall_mm=0.0,
        root_zone_replenishment_mm=0.0,
        irrigation_efficiency=0.9,
        validated_flow_m3h=25.0,
        flow_validation_status="validated",
        recent_irrigation_credit_status="verified_none",
        operating_window="approved window",
        weather_context={"eto_mm": 6.0},
    )

    result = engine.recommend(RecommendationRequest(field_context=field))

    assert result.action != "irrigate"
    assert result.recommended_duration_minutes is None
    assert "client_flow_validation_claim_withheld" in result.risk_flags
    assert "client_recent_water_verification_claim_withheld" in result.risk_flags

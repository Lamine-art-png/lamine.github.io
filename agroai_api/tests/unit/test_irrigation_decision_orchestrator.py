from app.services.irrigation_decision_orchestrator import IrrigationDecisionOrchestrator


def test_uploaded_artifact_context_runs_same_kernel():
    result = IrrigationDecisionOrchestrator().run(
        {
            "farm": "Alpha Vineyard",
            "block": "Block A North",
            "crop": "wine grapes",
            "soil": "clay loam",
            "irrigation_method": "drip",
            "area": 2.0,
            "field_notes": ["mild afternoon stress"],
            "source_kinds": ["weather", "soil_moisture", "flow_meter"],
            "metrics": {
                "avg_eto_mm": 6.4,
                "rain_forecast_total_mm": 0,
                "avg_deficit_percent": 40,
                "validated_flow_m3h": 28,
            },
        },
        mode="uploaded",
        origin="uploaded_intelligence_engine",
    )
    assert result["decision"]["recommendation_origin"] == "uploaded_intelligence_engine"
    assert result["decision"]["duration_minutes"] is not None


def test_partial_telemetry_does_not_fabricate_duration():
    result = IrrigationDecisionOrchestrator().run(
        {
            "farm": "Connected field",
            "block": "162803",
            "crop": "provider context pending",
            "soil": "provider context pending",
            "irrigation_method": "provider context pending",
            "metrics": {"avg_eto_mm": 6.0},
            "source_kinds": ["live_request"],
        },
        mode="live",
        origin="live_intelligence_engine",
    )
    assert result["decision"]["duration_minutes"] is None
    assert "validated_flow_or_application_rate" in result["decision"]["missing_inputs"]


def test_explicit_manual_overrides_improve_context():
    result = IrrigationDecisionOrchestrator().run(
        {"farm": "Manual", "block": "A", "metrics": {"avg_eto_mm": 6.0}},
        mode="live",
        origin="live_intelligence_engine",
        manual_overrides={
            "crop_type": "almonds",
            "soil_type": "loam",
            "irrigation_method": "micro-sprinkler",
            "area": 3.0,
            "sensor_context": {"flow_m3h": 30},
        },
    )
    assert result["decision"]["duration_minutes"] is not None
    assert result["manual_overrides_used"]

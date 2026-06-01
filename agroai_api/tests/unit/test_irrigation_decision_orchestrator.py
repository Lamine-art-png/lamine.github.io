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
                "evidence_reference_time": "2026-05-15T12:00:00Z",
            },
            "flow_evidence": {
                "value_m3h": 28,
                "provenance": "flow_meter",
                "block": "Block A North",
                "timestamp": "2026-05-15T06:00:00Z",
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
            "sensor_context": {
                "flow_m3h": 30,
                "flow_provenance": "flow_meter",
                "timestamp": "2026-05-15T06:00:00Z",
                "block": "A",
            },
        },
    )
    assert result["decision"]["duration_minutes"] is not None
    assert result["manual_overrides_used"]


def _base_context():
    return {
        "farm": "Alpha Vineyard",
        "block": "Block A North",
        "crop": "wine grapes",
        "soil": "clay loam",
        "irrigation_method": "drip",
        "area": 2.0,
        "source_kinds": ["weather", "soil_moisture", "flow_meter"],
        "metrics": {
            "avg_eto_mm": 6.4,
            "rain_forecast_total_mm": 0,
            "avg_deficit_percent": 40,
            "evidence_reference_time": "2026-05-15T12:00:00Z",
        },
        "flow_evidence": {
            "value_m3h": 28,
            "provenance": "controller_event",
            "block": "Block A North",
            "timestamp": "2026-05-15T06:00:00Z",
        },
    }


def test_stale_flow_evidence_withholds_duration():
    context = _base_context()
    context["flow_evidence"]["timestamp"] = "2026-05-01T06:00:00Z"
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["duration_minutes"] is None
    assert result["decision"]["flow_validation_status"] == "partial"


def test_inconsistent_flow_evidence_withholds_duration():
    context = _base_context()
    context["metrics"]["max_flow_variance_percent"] = 31
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["duration_minutes"] is None
    assert result["decision"]["flow_validation_status"] == "inconsistent"


def test_recent_verified_event_applies_credit():
    baseline = IrrigationDecisionOrchestrator().run(_base_context(), mode="uploaded", origin="uploaded_intelligence_engine")
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4,
        "block": "Block A North",
        "timestamp": "2026-05-15T06:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "verified_recent"
    assert result["decision"]["net_irrigation_depth_mm"] < baseline["decision"]["net_irrigation_depth_mm"]


def test_stale_recent_event_does_not_apply_credit():
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4,
        "block": "Block A North",
        "timestamp": "2026-05-01T06:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "stale"
    assert result["decision"]["calculation_trace"]["recent_verified_irrigation_credit_mm"] == 0.0


def test_wrong_block_recent_event_does_not_apply_credit():
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4,
        "block": "Block B West",
        "timestamp": "2026-05-15T06:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "unavailable"


def test_negative_depth_recent_event_does_not_apply_credit():
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": -4,
        "block": "Block A North",
        "timestamp": "2026-05-15T06:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "unavailable"


def test_missing_timestamp_recent_event_does_not_apply_credit():
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4,
        "block": "Block A North",
        "confirmation": "controller_confirmed",
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "partial"

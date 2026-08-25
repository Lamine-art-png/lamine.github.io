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
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
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
                "timestamp": recent_ts,
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


# --- Section 4: Recency calculation ------------------------------------------

def test_old_live_flow_event_is_stale_even_when_only_timestamp():
    """Without evidence_reference_time, the reference is wall-clock UTC.
    A very old flow event must be stale even if it is the only timestamp."""
    context = {
        "farm": "Live Farm",
        "block": "Zone 1",
        "crop": "wine grapes",
        "soil": "clay loam",
        "irrigation_method": "drip",
        "area": 2.0,
        "source_kinds": ["live_request"],
        "metrics": {
            "avg_eto_mm": 6.0,
            # No evidence_reference_time — reference falls back to datetime.now(UTC)
        },
        "flow_evidence": {
            "value_m3h": 28,
            "provenance": "controller_event",
            "block": "Zone 1",
            "timestamp": "2020-01-01T00:00:00Z",  # years old
        },
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="live", origin="live_intelligence_engine")
    assert result["decision"]["flow_validation_status"] in {"partial", "unavailable"}
    assert result["decision"]["duration_minutes"] is None


def test_old_live_irrigation_event_is_stale_even_when_only_timestamp():
    """Recent-credit events older than 72 h must be stale regardless of evidence_reference_time."""
    context = _base_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4,
        "block": "Block A North",
        "timestamp": "2020-01-01T00:00:00Z",  # years old
        "confirmation": "controller_confirmed",
    }
    # No evidence_reference_time in metrics → reference = datetime.now(UTC)
    del context["metrics"]["evidence_reference_time"]
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["recent_irrigation_credit_status"] == "stale"


def test_recent_live_event_is_accepted():
    """A flow event within 72 hours of wall-clock UTC is accepted."""
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    context = {
        "farm": "Live Farm",
        "block": "Zone 1",
        "crop": "wine grapes",
        "soil": "clay loam",
        "irrigation_method": "drip",
        "area": 2.0,
        "source_kinds": ["live_request"],
        "metrics": {"avg_eto_mm": 6.0},
        "flow_evidence": {
            "value_m3h": 28,
            "provenance": "flow_meter",
            "block": "Zone 1",
            "timestamp": recent_ts,
        },
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="live", origin="live_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "validated"


def test_uploaded_historical_package_uses_explicit_reference_timestamp():
    """When evidence_reference_time is set, recency is relative to that reference
    (not wall-clock UTC), so evidence older than wall-clock but within 72 h of the
    package reference is accepted."""
    from datetime import datetime, timezone, timedelta
    package_ref = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    evidence_ts = (package_ref - timedelta(hours=24)).isoformat()
    context = _base_context()
    context["metrics"]["evidence_reference_time"] = package_ref.isoformat()
    context["flow_evidence"]["timestamp"] = evidence_ts
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    # Evidence is 24 h before the explicit package reference — within the 72 h window.
    assert result["decision"]["flow_validation_status"] == "validated"
    assert result["evaluation_mode_label"] == "historical_package"


def test_missing_flow_timestamp_stays_partial():
    context = _base_context()
    context["flow_evidence"] = {
        "value_m3h": 28,
        "provenance": "controller_event",
        "block": "Block A North",
        # no timestamp
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "partial"
    assert result["decision"]["duration_minutes"] is None


# --- Section 5: Flow-meter-only evidence (orchestrator level) ----------------

def test_flow_meter_only_can_validate_duration():
    """Flow-meter provenance in the flow_evidence dict is accepted by the orchestrator."""
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    context = {
        "farm": "Beta Farm",
        "block": "Block B",
        "crop": "almonds",
        "soil": "loam",
        "irrigation_method": "drip",
        "area": 1.5,
        "source_kinds": ["flow_meter"],
        "metrics": {
            "avg_eto_mm": 5.0,
            "avg_deficit_percent": 35,
        },
        "flow_evidence": {
            "value_m3h": 22,
            "provenance": "flow_meter",
            "block": "Block B",
            "timestamp": recent_ts,
        },
    }
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "validated"
    assert result["decision"]["duration_minutes"] is not None


def test_controller_only_can_validate_duration():
    result = IrrigationDecisionOrchestrator().run(_base_context(), mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "validated"
    assert result["decision"]["duration_minutes"] is not None


def test_mismatched_flow_meter_block_is_rejected():
    context = _base_context()
    context["flow_evidence"]["block"] = "Block Z Wrong"
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "inconsistent"
    assert result["decision"]["duration_minutes"] is None


def test_stale_flow_meter_evidence_is_rejected():
    context = _base_context()
    context["flow_evidence"] = {
        "value_m3h": 28,
        "provenance": "flow_meter",
        "block": "Block A North",
        "timestamp": "2019-01-01T00:00:00Z",  # very old, no explicit reference → wall-clock
    }
    del context["metrics"]["evidence_reference_time"]
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] in {"partial", "unavailable"}


def test_inconsistent_flow_meter_variance_is_rejected():
    context = _base_context()
    context["metrics"]["max_flow_variance_percent"] = 35
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "inconsistent"


def test_negative_flow_is_rejected():
    context = _base_context()
    context["flow_evidence"]["value_m3h"] = -15
    result = IrrigationDecisionOrchestrator().run(context, mode="uploaded", origin="uploaded_intelligence_engine")
    assert result["decision"]["flow_validation_status"] == "unavailable"

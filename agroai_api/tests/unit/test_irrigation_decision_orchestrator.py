from copy import deepcopy

import pytest

from app.services.irrigation_decision_orchestrator import IrrigationDecisionOrchestrator


REFERENCE = "2026-05-15T12:00:00Z"


def _complete_context():
    return {
        "farm": "Alpha Vineyard",
        "block": "Block A North",
        "crop": "wine grapes",
        "soil": "clay loam",
        "irrigation_method": "drip",
        "area": 2.0,
        "crop_coefficient": 0.72,
        "effective_rainfall_mm": 0.0,
        "root_zone_replenishment_mm": 0.0,
        "irrigation_efficiency": 0.9,
        "operating_window": "customer-approved night window",
        "source_kinds": ["weather", "soil_moisture", "flow_meter", "controller_event"],
        "metrics": {
            "avg_eto_mm": 6.4,
            "evidence_reference_time": REFERENCE,
        },
        "flow_evidence": {
            "value_m3h": 28,
            "provenance": "flow_meter",
            "block": "Block A North",
            "timestamp": "2026-05-15T06:00:00Z",
            "valid_until": "2026-05-15T18:00:00Z",
            "pressure_state": "stable",
            "calibration_status": "current",
        },
        "recent_irrigation_evidence": {
            "no_recent_irrigation_confirmed": True,
            "confirmation": "controller_confirmed",
            "block": "Block A North",
            "timestamp": "2026-05-15T06:00:00Z",
            "valid_until": "2026-05-15T18:00:00Z",
        },
    }


def _run(context, *, mode="uploaded", overrides=None):
    return IrrigationDecisionOrchestrator().run(
        context,
        mode=mode,
        origin=f"{mode}_intelligence_engine",
        manual_overrides=overrides,
    )


def test_complete_explicit_package_computes_traceable_plan_for_approval():
    result = _run(_complete_context())
    decision = result["decision"]
    assert decision["decision_status"] == "ready_for_human_approval"
    assert decision["duration_minutes"] is not None
    assert decision["calibration_status"] == "explicit_evidence"
    assert decision["assumptions"] == []


def test_partial_telemetry_does_not_fabricate_depth_or_duration():
    result = _run(
        {
            "farm": "Connected field",
            "block": "162803",
            "crop": "provider context pending",
            "metrics": {"avg_eto_mm": 6.0},
            "source_kinds": ["live_request"],
        },
        mode="live",
    )
    assert result["decision"]["net_irrigation_depth_mm"] is None
    assert result["decision"]["duration_minutes"] is None
    assert result["decision"]["action"] == "insufficient_data"


def test_crop_and_method_labels_do_not_infer_scientific_parameters():
    context = _complete_context()
    del context["crop_coefficient"]
    del context["irrigation_efficiency"]
    result = _run(context)
    assert result["decision"]["net_irrigation_depth_mm"] is None
    assert result["decision"]["duration_minutes"] is None
    assert "crop_coefficient" in result["decision"]["missing_inputs"]
    assert "irrigation_efficiency" in result["decision"]["missing_inputs"]


def test_flow_without_explicit_validity_is_partial():
    context = _complete_context()
    del context["flow_evidence"]["valid_until"]
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "partial"
    assert result["decision"]["duration_minutes"] is None


def test_flow_can_use_explicit_caller_freshness_requirement():
    context = _complete_context()
    del context["flow_evidence"]["valid_until"]
    context["flow_evidence"]["max_age_hours"] = 8
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "validated"
    assert result["decision"]["duration_minutes"] is not None


def test_expired_flow_validity_withholds_duration():
    context = _complete_context()
    context["flow_evidence"]["valid_until"] = "2026-05-15T08:00:00Z"
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "partial"
    assert result["decision"]["duration_minutes"] is None


def test_wrong_block_flow_is_inconsistent():
    context = _complete_context()
    context["flow_evidence"]["block"] = "Block Z Wrong"
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "inconsistent"
    assert result["decision"]["duration_minutes"] is None


def test_flow_requires_stable_pressure_and_current_calibration():
    pressure = _complete_context()
    del pressure["flow_evidence"]["pressure_state"]
    assert _run(pressure)["decision"]["flow_validation_status"] == "partial"

    calibration = _complete_context()
    del calibration["flow_evidence"]["calibration_status"]
    assert _run(calibration)["decision"]["flow_validation_status"] == "partial"


def test_observed_variance_requires_explicit_acceptance_limit():
    context = _complete_context()
    context["metrics"]["max_flow_variance_percent"] = 12
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "partial"


def test_explicit_variance_limit_is_enforced():
    context = _complete_context()
    context["metrics"]["max_flow_variance_percent"] = 12
    context["flow_evidence"]["max_variance_percent"] = 10
    result = _run(context)
    assert result["decision"]["flow_validation_status"] == "inconsistent"


def test_verified_recent_event_applies_exact_uncapped_credit():
    baseline = _run(_complete_context())["decision"]
    context = _complete_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4.0,
        "block": "Block A North",
        "timestamp": "2026-05-15T06:00:00Z",
        "valid_until": "2026-05-15T18:00:00Z",
        "confirmation": "controller_confirmed",
    }
    decision = _run(context)["decision"]
    assert decision["recent_irrigation_credit_status"] == "verified_recent"
    assert decision["net_irrigation_depth_mm"] == pytest.approx(
        baseline["net_irrigation_depth_mm"] - 4.0
    )


def test_recent_credit_without_validity_is_not_applied():
    context = _complete_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4.0,
        "block": "Block A North",
        "timestamp": "2026-05-15T06:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = _run(context)
    assert result["decision"]["recent_irrigation_credit_status"] == "partial"
    assert result["decision"]["net_irrigation_depth_mm"] is None


def test_expired_recent_credit_is_stale_and_not_applied():
    context = _complete_context()
    context["recent_irrigation_evidence"] = {
        "depth_mm": 4.0,
        "block": "Block A North",
        "timestamp": "2026-05-15T06:00:00Z",
        "valid_until": "2026-05-15T08:00:00Z",
        "confirmation": "controller_confirmed",
    }
    result = _run(context)
    assert result["decision"]["recent_irrigation_credit_status"] == "stale"
    assert result["decision"]["net_irrigation_depth_mm"] is None


def test_missing_operating_window_never_emits_operational_action():
    context = _complete_context()
    del context["operating_window"]
    decision = _run(context)["decision"]
    assert decision["duration_minutes"] is not None
    assert decision["timing_window"] is None
    assert decision["action"] == "inspect"


def test_explicit_net_requirement_bypasses_no_missing_water_balance_inputs():
    context = _complete_context()
    context["net_irrigation_requirement_mm"] = 3.0
    del context["metrics"]["avg_eto_mm"]
    del context["crop_coefficient"]
    del context["effective_rainfall_mm"]
    del context["root_zone_replenishment_mm"]
    decision = _run(context)["decision"]
    assert decision["net_irrigation_depth_mm"] == 3.0
    assert decision["decision_status"] == "ready_for_human_approval"


def test_manual_override_is_subject_to_same_validation_gates():
    base = _complete_context()
    del base["flow_evidence"]
    override = {
        "sensor_context": {
            "flow_m3h": 30,
            "flow_provenance": "flow_meter",
            "timestamp": "2026-05-15T06:00:00Z",
            "block": "Block A North",
        }
    }
    result = _run(base, overrides=override)
    assert result["decision"]["flow_validation_status"] == "partial"
    assert result["decision"]["duration_minutes"] is None
    assert result["manual_overrides_used"] == ["sensor_context"]


def test_negative_flow_is_rejected_without_clamping():
    context = deepcopy(_complete_context())
    context["flow_evidence"]["value_m3h"] = -15
    decision = _run(context)["decision"]
    assert decision["flow_validation_status"] == "unavailable"
    assert decision["duration_minutes"] is None

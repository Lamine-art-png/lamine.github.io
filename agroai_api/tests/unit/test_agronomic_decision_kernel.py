import pytest

from app.services.agronomic_decision_kernel import AgronomicDecisionKernelV02


def _complete(**overrides):
    payload = {
        "eto_mm": 6.4,
        "crop_type": "wine grapes",
        "crop_coefficient": 0.72,
        "effective_rainfall_mm": 0.0,
        "root_zone_replenishment_mm": 0.0,
        "recent_irrigation_credit_status": "verified_none",
        "irrigation_method": "drip",
        "irrigation_efficiency": 0.9,
        "field_area_ha": 2.0,
        "flow_rate_m3h": 28.0,
        "flow_validation_status": "validated",
        "operating_window": "customer-approved night window",
    }
    payload.update(overrides)
    return payload


def test_complete_explicit_evidence_computes_plan_for_human_approval():
    result = AgronomicDecisionKernelV02().compute(_complete())
    assert result["action"] == "irrigate"
    assert result["decision_status"] == "ready_for_human_approval"
    assert result["duration_minutes"] is not None
    assert result["calibration_status"] == "explicit_evidence"
    assert result["assumptions"] == []


def test_crop_label_never_resolves_a_silent_crop_coefficient():
    payload = _complete()
    payload.pop("crop_coefficient")
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["action"] == "insufficient_data"
    assert result["net_irrigation_depth_mm"] is None
    assert result["gross_irrigation_depth_mm"] is None
    assert result["duration_minutes"] is None
    assert "crop_coefficient" in result["missing_inputs"]


def test_method_label_never_resolves_a_silent_efficiency():
    payload = _complete()
    payload.pop("irrigation_efficiency")
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["net_irrigation_depth_mm"] is not None
    assert result["gross_irrigation_depth_mm"] is None
    assert result["duration_minutes"] is None
    assert "irrigation_efficiency" in result["missing_inputs"]


def test_missing_effective_rainfall_does_not_apply_a_forecast_fraction():
    payload = _complete(precipitation_forecast_mm=5.0)
    payload.pop("effective_rainfall_mm")
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["action"] == "insufficient_data"
    assert result["net_irrigation_depth_mm"] is None
    assert "effective_rainfall_mm" in result["missing_inputs"]


def test_missing_root_zone_replenishment_remains_missing():
    payload = _complete()
    payload.pop("root_zone_replenishment_mm")
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["net_irrigation_depth_mm"] is None
    assert "root_zone_replenishment_mm" in result["missing_inputs"]


def test_missing_flow_withholds_duration_and_action():
    payload = _complete(flow_rate_m3h=None, flow_validation_status="unavailable")
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["duration_minutes"] is None
    assert result["action"] == "inspect"
    assert "validated_flow_or_application_rate" in result["missing_inputs"]
    assert "Duration withheld" in result["duration_basis"]


def test_missing_operating_window_withholds_irrigation_action_but_keeps_traceable_calculation():
    payload = _complete(operating_window=None)
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["duration_minutes"] is not None
    assert result["timing_window"] is None
    assert result["action"] == "inspect"
    assert "approved_operating_window" in result["missing_inputs"]


def test_explicit_net_requirement_can_be_used_without_reconstructing_root_zone_state():
    payload = _complete(net_irrigation_requirement_mm=4.0)
    for key in ("eto_mm", "crop_coefficient", "effective_rainfall_mm", "root_zone_replenishment_mm"):
        payload.pop(key)
    result = AgronomicDecisionKernelV02().compute(payload)
    assert result["action"] == "irrigate"
    assert result["net_irrigation_depth_mm"] == 4.0
    assert result["calculation_trace"]["net_requirement_basis"] == "explicit_net_irrigation_requirement"


def test_verified_recent_irrigation_credit_is_not_capped_or_assumed():
    baseline = AgronomicDecisionKernelV02().compute(_complete())
    credited = AgronomicDecisionKernelV02().compute(
        _complete(recent_irrigation_depth_mm=2.0, recent_irrigation_credit_status="verified_recent")
    )
    assert credited["net_irrigation_depth_mm"] == pytest.approx(
        baseline["net_irrigation_depth_mm"] - 2.0
    )


def test_explicit_zero_net_requirement_supports_wait_without_schedule():
    result = AgronomicDecisionKernelV02().compute(
        _complete(net_irrigation_requirement_mm=0.0, operating_window=None)
    )
    assert result["action"] == "wait"
    assert result["decision_status"] == "supported_no_irrigation_requirement"
    assert result["duration_minutes"] == 0.0


def test_invalid_inputs_are_withheld_not_clamped_to_plausible_looking_values():
    result = AgronomicDecisionKernelV02().compute(
        _complete(crop_coefficient=-1.0, irrigation_efficiency=2.0, field_area_ha=-2.0, flow_rate_m3h=-5.0)
    )
    assert result["action"] == "insufficient_data"
    assert result["duration_minutes"] is None
    assert result["validation_warnings"]
    assert all("clamped" not in warning for warning in result["validation_warnings"])

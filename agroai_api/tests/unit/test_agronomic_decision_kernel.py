from app.services.agronomic_decision_kernel import AgronomicDecisionKernelV02


def test_calibrated_vineyard_case_computes_duration_from_flow():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "soil_moisture_deficit_pct": 40,
            "field_area_ha": 2.0,
            "flow_rate_m3h": 28,
            "flow_validation_status": "validated",
        }
    )
    assert result["action"] == "irrigate"
    assert result["duration_minutes"] is not None
    assert result["calibration_status"] == "calibrated_context"


def test_almond_case_uses_almond_calibration():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.8,
            "crop_type": "almonds",
            "soil_type": "loam",
            "irrigation_method": "micro-sprinkler",
            "soil_moisture_deficit_pct": 55,
            "field_area_ha": 4.0,
            "flow_rate_m3h": 42,
            "flow_validation_status": "validated",
        }
    )
    assert result["action"] == "irrigate"
    assert result["gross_irrigation_depth_mm"] > result["net_irrigation_depth_mm"]


def test_rain_wait_case():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 4.0,
            "crop_type": "citrus",
            "soil_type": "loam",
            "irrigation_method": "drip",
            "precipitation_forecast_mm": 5.0,
            "field_area_ha": 1.0,
            "flow_rate_m3h": 20,
            "flow_validation_status": "validated",
        }
    )
    assert result["action"] == "wait"


def test_missing_flow_rate_withholds_duration():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 7.0,
            "crop_type": "vegetables",
            "soil_type": "sand",
            "irrigation_method": "sprinkler",
            "field_area_ha": 1.2,
        }
    )
    assert result["duration_minutes"] is None
    assert "Duration withheld" in " ".join(result["limitations"])


def test_missing_crop_and_soil_exposes_assumptions():
    result = AgronomicDecisionKernelV02().compute({"eto_mm": 5.0, "field_area_ha": 1.0, "flow_rate_m3h": 10})
    assert result["calibration_status"] in {"assumptions_required", "partial_calibration"}
    assert result["assumptions"]


def test_inconsistent_flow_withholds_duration():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "field_area_ha": 2.0,
            "flow_rate_m3h": 28,
            "flow_validation_status": "inconsistent",
        }
    )
    assert result["duration_minutes"] is None
    assert result["flow_validation_status"] == "inconsistent"


def test_stale_flow_withholds_duration():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "field_area_ha": 2.0,
            "flow_rate_m3h": 28,
            "flow_validation_status": "partial",
        }
    )
    assert result["duration_minutes"] is None
    assert "Duration withheld until validated flow evidence is available." in result["limitations"]


def test_negative_flow_withholds_duration():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "field_area_ha": 2.0,
            "flow_rate_m3h": -28,
            "flow_validation_status": "validated",
        }
    )
    assert result["duration_minutes"] is None
    assert any("flow_rate_m3h" in warning for warning in result["validation_warnings"])


def test_recent_verified_irrigation_credit_reduces_need():
    without_credit = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "field_area_ha": 2.0,
            "flow_rate_m3h": 28,
            "flow_validation_status": "validated",
        }
    )
    with_credit = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": 6.4,
            "crop_type": "wine grapes",
            "soil_type": "clay loam",
            "irrigation_method": "drip",
            "field_area_ha": 2.0,
            "flow_rate_m3h": 28,
            "flow_validation_status": "validated",
            "recent_irrigation_depth_mm": 4,
            "recent_irrigation_credit_status": "verified_recent",
        }
    )
    assert with_credit["net_irrigation_depth_mm"] < without_credit["net_irrigation_depth_mm"]


def test_invalid_inputs_are_clamped_or_withheld():
    result = AgronomicDecisionKernelV02().compute(
        {
            "eto_mm": -2,
            "precipitation_forecast_mm": -4,
            "crop_coefficient": 9,
            "irrigation_efficiency": 2,
            "soil_moisture_deficit_pct": 180,
            "root_zone_depth_mm": -50,
            "field_area_ha": -1,
            "controller_capacity_m3h": -10,
            "flow_validation_status": "validated",
        }
    )
    assert result["duration_minutes"] is None
    assert result["validation_warnings"]

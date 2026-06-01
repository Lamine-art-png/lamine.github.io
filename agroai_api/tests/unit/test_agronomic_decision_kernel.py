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

from app.services.scientific_tool_registry import get_scientific_tool_registry


def test_registry_exposes_all_initial_versioned_tools():
    specs = {spec.tool_id: spec for spec in get_scientific_tool_registry().specs()}
    assert {
        "fao56.etc.single_kc.v1",
        "irrigation.measured_volume.v1",
        "irrigation.applied_depth.v1",
        "irrigation.volume_from_depth.v1",
        "irrigation.gross_requirement.v1",
        "irrigation.duration_from_validated_flow.v1",
        "units.convert.v1",
        "evidence.freshness.v1",
        "sensor.plausibility.v1",
    } <= set(specs)
    assert all(spec.version and spec.required_inputs and spec.calculation_method for spec in specs.values())
    assert all(spec.valid_ranges for spec in specs.values())
    assert all(spec.unit_normalization or not spec.expected_units for spec in specs.values())


def test_etc_requires_explicit_kc_and_never_infers_it():
    result = get_scientific_tool_registry().run("fao56.etc.single_kc.v1", {"eto_mm": 5.0})
    assert result.status == "NOT_COMPUTABLE"
    assert result.missing_requirements == ["kc"]


def test_etc_computes_only_from_supplied_inputs():
    result = get_scientific_tool_registry().run("fao56.etc.single_kc.v1", {"eto_mm": 5.0, "kc": 0.8})
    assert result.status == "COMPUTED"
    assert result.output["etc_mm"] == 4.0


def test_measured_volume_from_flow_and_runtime():
    result = get_scientific_tool_registry().run(
        "irrigation.measured_volume.v1", {"flow_m3h": 12.0, "runtime_minutes": 30.0}
    )
    assert result.output["volume_m3"] == 6.0


def test_applied_depth_and_volume_are_inverse_in_si_units():
    registry = get_scientific_tool_registry()
    volume = registry.run("irrigation.volume_from_depth.v1", {"depth_mm": 7.5, "area_ha": 2.0})
    depth = registry.run("irrigation.applied_depth.v1", {"volume_m3": volume.output["volume_m3"], "area_ha": 2.0})
    assert volume.output["volume_m3"] == 150.0
    assert depth.output["depth_mm"] == 7.5


def test_gross_requirement_requires_valid_explicit_efficiency():
    registry = get_scientific_tool_registry()
    missing = registry.run("irrigation.gross_requirement.v1", {"net_requirement_mm": 5.0})
    invalid = registry.run("irrigation.gross_requirement.v1", {"net_requirement_mm": 5.0, "efficiency": 1.2})
    valid = registry.run("irrigation.gross_requirement.v1", {"net_requirement_mm": 5.0, "efficiency": 0.8})
    assert missing.status == "NOT_COMPUTABLE"
    assert invalid.status == "INVALID_INPUT"
    assert valid.output["gross_requirement_mm"] == 6.25


def test_duration_requires_validated_flow_input():
    registry = get_scientific_tool_registry()
    missing = registry.run("irrigation.duration_from_validated_flow.v1", {"required_volume_m3": 10.0})
    valid = registry.run(
        "irrigation.duration_from_validated_flow.v1",
        {"required_volume_m3": 10.0, "validated_flow_m3h": 20.0},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert valid.output["duration_minutes"] == 30.0


def test_unit_conversion_rejects_dimension_mismatch():
    registry = get_scientific_tool_registry()
    converted = registry.run("units.convert.v1", {"value": 1.0, "from_unit": "in", "to_unit": "mm"})
    invalid = registry.run("units.convert.v1", {"value": 1.0, "from_unit": "in", "to_unit": "l"})
    assert converted.output["value"] == 25.4
    assert invalid.status == "INVALID_INPUT"


def test_freshness_requires_caller_supplied_threshold():
    registry = get_scientific_tool_registry()
    missing = registry.run(
        "evidence.freshness.v1",
        {"observed_at": "2026-08-21T00:00:00Z", "evaluated_at": "2026-08-21T12:00:00Z"},
    )
    fresh = registry.run(
        "evidence.freshness.v1",
        {
            "observed_at": "2026-08-21T00:00:00Z",
            "evaluated_at": "2026-08-21T12:00:00Z",
            "max_age_hours": 24.0,
        },
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert fresh.output == {"age_hours": 12.0, "fresh": True}


def test_sensor_plausibility_uses_explicit_bounds_only():
    registry = get_scientific_tool_registry()
    missing = registry.run("sensor.plausibility.v1", {"value": 25.0})
    checked = registry.run(
        "sensor.plausibility.v1",
        {"value": 25.0, "min_value": 0.0, "max_value": 20.0, "unit": "source_native"},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert checked.output["plausible"] is False


def test_unit_conversion_and_plausibility_support_finite_negative_values_without_guessing_bounds():
    registry = get_scientific_tool_registry()
    converted = registry.run("units.convert.v1", {"value": -2.0, "from_unit": "m", "to_unit": "mm"})
    checked = registry.run(
        "sensor.plausibility.v1",
        {"value": -5.0, "min_value": -10.0, "max_value": 0.0, "unit": "source_native"},
    )
    assert converted.output["value"] == -2000.0
    assert checked.output["plausible"] is True

import pytest

from app.services.scientific_tool_registry import get_scientific_tool_registry


def test_extended_registry_has_science_accounting_tools_without_defaults():
    ids = {spec.tool_id for spec in get_scientific_tool_registry().specs()}
    assert {
        "soil.total_available_water.v1",
        "soil.root_zone_storage.v1",
        "soil.depletion_from_field_capacity.v1",
        "soil.readily_available_water.v1",
        "water.balance.identity.v1",
        "irrigation.distribution_uniformity_lq.v1",
        "phenology.gdd.simple_average.v1",
        "nutrients.mass_from_solution.v1",
        "nutrients.mass_from_product_fraction.v1",
        "evidence.numeric_agreement.v1",
    } <= ids


def test_total_available_water_requires_explicit_fc_wp_and_root_depth():
    registry = get_scientific_tool_registry()
    missing = registry.run(
        "soil.total_available_water.v1",
        {"field_capacity_vwc_fraction": 0.30, "wilting_point_vwc_fraction": 0.12},
    )
    valid = registry.run(
        "soil.total_available_water.v1",
        {"field_capacity_vwc_fraction": 0.30, "wilting_point_vwc_fraction": 0.12, "root_zone_depth_m": 0.8},
    )
    invalid = registry.run(
        "soil.total_available_water.v1",
        {"field_capacity_vwc_fraction": 0.10, "wilting_point_vwc_fraction": 0.12, "root_zone_depth_m": 0.8},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert missing.missing_requirements == ["root_zone_depth_m"]
    assert valid.output["total_available_water_mm"] == pytest.approx(144.0)
    assert invalid.status == "INVALID_INPUT"


def test_root_zone_depletion_preserves_above_field_capacity_signal_without_clamping():
    registry = get_scientific_tool_registry()
    result = registry.run(
        "soil.depletion_from_field_capacity.v1",
        {"field_capacity_vwc_fraction": 0.30, "current_vwc_fraction": 0.34, "root_zone_depth_m": 0.5},
    )
    assert result.status == "COMPUTED"
    assert result.output["depletion_from_field_capacity_mm"] == pytest.approx(-20.0)
    assert result.output["above_field_capacity"] is True


def test_readily_available_water_requires_explicit_management_fraction():
    registry = get_scientific_tool_registry()
    missing = registry.run("soil.readily_available_water.v1", {"total_available_water_mm": 144.0})
    valid = registry.run(
        "soil.readily_available_water.v1",
        {"total_available_water_mm": 144.0, "management_allowable_depletion_fraction": 0.45},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert valid.output["readily_available_water_mm"] == pytest.approx(64.8)


def test_water_balance_is_conservation_identity_and_keeps_negative_closing_storage():
    registry = get_scientific_tool_registry()
    result = registry.run(
        "water.balance.identity.v1",
        {
            "opening_storage_mm": 10.0,
            "effective_rainfall_mm": 1.0,
            "irrigation_mm": 0.0,
            "capillary_rise_mm": 0.0,
            "crop_et_mm": 12.0,
            "runoff_mm": 0.0,
            "deep_percolation_mm": 1.0,
        },
    )
    assert result.status == "COMPUTED"
    assert result.output["inflow_mm"] == 1.0
    assert result.output["outflow_mm"] == 13.0
    assert result.output["storage_change_mm"] == -12.0
    assert result.output["closing_storage_mm"] == -2.0


def test_distribution_uniformity_requires_exact_lower_quarter_sample_count():
    registry = get_scientific_tool_registry()
    values = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    valid = registry.run(
        "irrigation.distribution_uniformity_lq.v1",
        {"application_depths_mm": values, "lower_quarter_count": 2},
    )
    invalid = registry.run(
        "irrigation.distribution_uniformity_lq.v1",
        {"application_depths_mm": values, "lower_quarter_count": 1},
    )
    assert valid.status == "COMPUTED"
    assert valid.output["lower_quarter_average_mm"] == 8.5
    assert valid.output["overall_average_mm"] == 11.5
    assert valid.output["distribution_uniformity_fraction"] == pytest.approx(8.5 / 11.5)
    assert invalid.status == "INVALID_INPUT"


def test_simple_gdd_requires_explicit_base_and_does_not_infer_temperature_caps():
    registry = get_scientific_tool_registry()
    missing = registry.run("phenology.gdd.simple_average.v1", {"tmax_c": 30.0, "tmin_c": 10.0})
    valid = registry.run(
        "phenology.gdd.simple_average.v1",
        {"tmax_c": 30.0, "tmin_c": 10.0, "base_temperature_c": 12.0},
    )
    cold = registry.run(
        "phenology.gdd.simple_average.v1",
        {"tmax_c": 10.0, "tmin_c": 4.0, "base_temperature_c": 12.0},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert valid.output["gdd_c_days"] == 8.0
    assert cold.output["raw_degree_days_c"] == -5.0
    assert cold.output["gdd_c_days"] == 0.0


def test_nutrient_tools_are_mass_accounting_not_dose_recommendations():
    registry = get_scientific_tool_registry()
    solution = registry.run(
        "nutrients.mass_from_solution.v1",
        {"concentration_mg_l": 100.0, "solution_volume_m3": 20.0},
    )
    product = registry.run(
        "nutrients.mass_from_product_fraction.v1",
        {"product_mass_kg": 50.0, "nutrient_mass_fraction": 0.20},
    )
    assert solution.output["solute_mass_kg"] == 2.0
    assert product.output["nutrient_mass_kg"] == 10.0
    assert any("does not recommend" in item.casefold() or "does not determine" in item.casefold() for item in solution.limitations + product.limitations)


def test_numeric_agreement_requires_explicit_tolerance_and_mode():
    registry = get_scientific_tool_registry()
    missing = registry.run("evidence.numeric_agreement.v1", {"value_a": 100.0, "value_b": 110.0})
    relative = registry.run(
        "evidence.numeric_agreement.v1",
        {"value_a": 100.0, "value_b": 110.0, "tolerance": 0.10, "mode": "relative"},
    )
    absolute = registry.run(
        "evidence.numeric_agreement.v1",
        {"value_a": 100.0, "value_b": 110.0, "tolerance": 5.0, "mode": "absolute"},
    )
    assert missing.status == "NOT_COMPUTABLE"
    assert relative.output["within_tolerance"] is True
    assert absolute.output["within_tolerance"] is False


def test_unit_registry_now_supports_mass_and_days_without_cross_dimension_conversion():
    registry = get_scientific_tool_registry()
    pounds = registry.run("units.convert.v1", {"value": 10.0, "from_unit": "lb", "to_unit": "kg"})
    days = registry.run("units.convert.v1", {"value": 2.0, "from_unit": "day", "to_unit": "h"})
    invalid = registry.run("units.convert.v1", {"value": 2.0, "from_unit": "kg", "to_unit": "l"})
    assert pounds.output["value"] == pytest.approx(4.5359237)
    assert days.output["value"] == 48.0
    assert invalid.status == "INVALID_INPUT"

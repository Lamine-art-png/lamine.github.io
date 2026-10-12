"""Crop Intelligence estimators exposed through the scientific tool registry.

Inputs are constructed test fixtures with hand-computed expectations; they
are not agronomic results.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.scientific_tool_registry import get_scientific_tool_registry

HARVEST = "crop.harvest_window.analog_years.v1"
PRODUCTION = "crop.production.sampling_estimate.v1"
STAGES = "crop.maturity.stage_proportions.v1"


def _days(start: date, count: int, tmax: float, tmin: float = 10.0) -> list[dict]:
    return [{"date": (start + timedelta(days=offset)).isoformat(), "tmax_c": tmax, "tmin_c": tmin} for offset in range(count)]


def _harvest(**overrides):
    values = {
        "biofix": "2026-04-01", "biofix_type": "planting", "as_of": "2026-04-30",
        "degree_day_method": "modified_average_86_50", "base_c": 10.0, "upper_cutoff_c": 30.0,
        "target_low_gdd": 1000, "target_high_gdd": 1200,
        "target_source": "Seed supplier hybrid sheet (test)", "target_source_type": "supplier_published",
        "observed_weather": _days(date(2026, 4, 1), 30, 30), "observed_source": "test station 1",
        "analog_years": {str(year): _days(date(year, 1, 1), 366 if year % 4 == 0 else 365, 30) for year in range(2019, 2024)},
        "analog_source": "test station 1 history",
    }
    values.update(overrides)
    return values


def _production(**overrides):
    values = {
        "unit": "vine", "object_label": "cluster", "design": "systematic_random_start", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "manual_count",
        "detection_rate": {"value": 0.8, "standard_error": 0.04},
        "unit_weight_kg": {"value": 0.15, "standard_error": 0.0075}, "area_hectares": 0.5,
    }
    values.update(overrides)
    return values


def _stages(**overrides):
    values = {
        "crop": "almond", "design": "simple_random", "count_source": "manual_count",
        "samples": [{"unit_id": f"tree-{i}", "counts": {"hull_split": s, "hull_intact": 10 - s}} for i, s in enumerate((2, 4, 6, 3, 5))],
    }
    values.update(overrides)
    return values


def test_crop_tools_are_registered_with_explicit_requirements():
    specs = {spec.tool_id: spec for spec in get_scientific_tool_registry().specs()}
    assert {HARVEST, PRODUCTION, STAGES} <= set(specs)
    assert {"target_source", "observed_source", "analog_source"} <= set(specs[HARVEST].required_inputs)
    assert {"design", "count_source", "population_units"} <= set(specs[PRODUCTION].required_inputs)
    assert "detector_validation_id" in specs[STAGES].optional_inputs
    for tool_id in (HARVEST, PRODUCTION, STAGES):
        assert specs[tool_id].limitations, tool_id


def test_harvest_window_tool_matches_the_estimator():
    result = get_scientific_tool_registry().run(HARVEST, _harvest())
    assert result.status == "COMPUTED"
    assert result.output["status"] == "projected"
    assert result.output["accumulated_gdd"] == 300.0
    assert result.output["window"]["earliest"] == "2026-07-09"
    assert result.output["window"]["latest"] == "2026-07-29"
    assert result.normalized_inputs["analog_years"] == [2019, 2020, 2021, 2022, 2023]


def test_production_tool_matches_the_estimator():
    result = get_scientific_tool_registry().run(PRODUCTION, _production())
    assert result.status == "COMPUTED"
    assert result.output["status"] == "estimated"
    assert result.output["expected_production_kg"]["value"] == 187.5
    assert result.output["expected_production_kg"]["interval_95"] == pytest.approx([136.1, 238.9], abs=0.2)
    assert result.output["input_provenance"]


def test_stage_tool_matches_the_estimator():
    result = get_scientific_tool_registry().run(STAGES, _stages(readiness={"ready_stages": ["hull_split"], "threshold_share": 0.2,
                                                                           "source": "Grower harvest plan (test)"}))
    assert result.status == "COMPUTED"
    assert result.output["stage_shares"]["hull_split"]["share"] == 0.4
    assert result.output["stage_shares"]["hull_split"]["interval_95"] == pytest.approx([0.2037, 0.5963], abs=1e-4)
    assert result.output["readiness"]["status"] == "ready"


@pytest.mark.parametrize(
    ("tool_id", "inputs", "missing"),
    [
        (HARVEST, _harvest(target_source=None), "target_source"),
        (HARVEST, _harvest(analog_source=None), "analog_source"),
        (PRODUCTION, _production(population_units=None), "population_units"),
        (STAGES, _stages(count_source=None), "count_source"),
    ],
)
def test_missing_requirements_are_not_computable(tool_id, inputs, missing):
    result = get_scientific_tool_registry().run(tool_id, inputs)
    assert result.status == "NOT_COMPUTABLE"
    assert missing in result.missing_requirements
    assert result.output == {}


@pytest.mark.parametrize(
    ("tool_id", "inputs", "reason"),
    [
        (HARVEST, _harvest(analog_years={"2019": _days(date(2019, 1, 1), 365, 30)}), "analog_years_usable:1<5"),
        (HARVEST, _harvest(target_source_type="model_knowledge"), "maturity_target_source_type_not_accepted"),
        (HARVEST, _harvest(base_c=float("nan")), "base_c_must_be_a_finite_number"),
        (HARVEST, _harvest(observed_weather=[{"date": "2026-04-01", "tmax_c": "30", "tmin_c": 10}]), "observed_weather.tmax_c_must_be_a_finite_number"),
        (HARVEST, _harvest(as_of="April 30"), "as_of_must_be_an_iso_date"),
        (PRODUCTION, _production(sample_counts=[10, float("inf"), 8, 11, 9]), "sample_counts_must_be_a_finite_number"),
        (PRODUCTION, _production(unit_weight_kg={"value": float("nan"), "standard_error": 0.01}), "unit_weight_kg.value_must_be_a_finite_number"),
        (PRODUCTION, _production(area_hectares=10 ** 400), "area_hectares_must_be_a_finite_number"),
        (PRODUCTION, _production(population_units=100.5), "population_units_must_be_an_integer"),
        (PRODUCTION, _production(design="convenience_walk"), "non_probability_sample_cannot_be_extrapolated"),
        (PRODUCTION, _production(count_source="validated_detector", detector_validation_id="eval-trust-me"),
         "detector_evaluation_not_in_server_registry"),
        (STAGES, _stages(crop="dragonfruit"), "crop_profile_not_supported"),
        (STAGES, _stages(count_source="validated_detector", detector_validation_id="trust-me"), "detector_evaluation_not_in_server_registry"),
        (STAGES, _stages(readiness={"ready_stages": ["hull_split"], "threshold_share": 0.2, "source": " "}),
         "readiness_threshold_source_required"),
    ],
)
def test_unsupported_inputs_are_rejected_with_exact_reasons(tool_id, inputs, reason):
    result = get_scientific_tool_registry().run(tool_id, inputs)
    assert result.status == "INVALID_INPUT"
    assert reason in result.invalid_inputs[0].split(";")
    assert result.output == {}


def test_oversized_inputs_are_rejected_before_computation():
    registry = get_scientific_tool_registry()
    too_many_years = {str(year): [] for year in range(1980, 2020)}
    assert registry.run(HARVEST, _harvest(analog_years=too_many_years)).status == "INVALID_INPUT"
    assert registry.run(PRODUCTION, _production(sample_counts=[1] * 2001)).status == "INVALID_INPUT"


def test_platform_tool_registry_exposes_the_crop_tools():
    from app.intelligence_platform.tools import _build_registry

    tools = {tool.name: tool for tool in _build_registry().all()}
    assert {HARVEST, PRODUCTION, STAGES} <= set(tools)
    assert tools[STAGES].category == "calculation"
    assert "crop" in tools[STAGES].input_schema["required"]
    completed = tools[PRODUCTION].handler(None, _production())
    assert completed["status"] == "completed" and completed["output"]["expected_production_kg"]["value"] == 187.5
    refused = tools[PRODUCTION].handler(None, _production(design="convenience_walk"))
    assert refused["status"] == "invalid_input" and refused["output"] == {}


def test_stratified_production_through_the_registry_is_population_weighted():
    registry = get_scientific_tool_registry()
    strata = [{"stratum_id": "high-load", "population_units": 10, "sample_counts": [10] * 5},
              {"stratum_id": "low-load", "population_units": 90, "sample_counts": [1] * 5}]
    result = registry.run(PRODUCTION, _production(design="stratified_random", sample_counts=None, strata=strata,
                                                  detection_rate=None, unit_weight_kg=None))
    assert result.status == "COMPUTED"
    assert result.output["extrapolated_visible_objects"]["value"] == 190.0
    assert result.normalized_inputs["strata"] == 2

    refused = registry.run(PRODUCTION, _production(design="stratified_random"))
    assert refused.status == "INVALID_INPUT"
    assert "stratified_random_requires_at_least_2_strata_with_population_and_samples" in refused.invalid_inputs[0].split(";")


@pytest.mark.parametrize(
    ("tool_id", "inputs", "reason"),
    [
        (PRODUCTION, _production(sample_counts=[10, 1e8, 8, 11, 9]), "sample_counts_out_of_range"),
        (PRODUCTION, _production(population_units=10 ** 9), "population_units_out_of_range"),
        (PRODUCTION, _production(unit_weight_kg={"value": 1e300, "standard_error": 1e300}), "unit_weight_kg.value_out_of_range"),
        (PRODUCTION, _production(design="stratified_random", sample_counts=None,
                                 strata=[{"stratum_id": "a", "population_units": 10 ** 9, "sample_counts": [1, 2]},
                                         {"stratum_id": "b", "population_units": 10, "sample_counts": [1, 2]}]),
         "stratum_population_units_out_of_range"),
        (STAGES, _stages(samples=[{"unit_id": "t", "counts": {"hull_split": 1e200}}]), "samples.hull_split_out_of_range"),
    ],
)
def test_out_of_range_numbers_are_rejected_before_computation(tool_id, inputs, reason):
    result = get_scientific_tool_registry().run(tool_id, inputs)
    assert result.status == "INVALID_INPUT"
    assert reason in result.invalid_inputs[0].split(";")

"""Crop Intelligence estimators exposed through the scientific tool registry.

Registering them in the existing fail-closed registry makes them available
to every existing consumer (Platform API intelligence runs, specialists, the
decision kernel) without a parallel system or new endpoints. Inputs are
parsed strictly; an estimator that cannot answer raises ``ValueError`` with
its exact reasons, which the registry reports as ``INVALID_INPUT``.
"""
from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from app.services import crop_estimation as est
from app.services.crop_profiles import resolve_profile

MAX_WEATHER_DAYS = 400
MAX_ANALOG_YEARS = 30
MAX_SAMPLE_UNITS = 2000
MAX_STRATA = 50
# Same bounds as the HTTP routes, so squares and products stay far inside float range.
MAX_COUNT_PER_UNIT = 10_000_000.0
MAX_ESTIMATE_INPUT = 1_000_000.0
MAX_POPULATION_UNITS = 100_000_000
# Harvest-window bounds, as on the HTTP route.
MAX_BASE_C = 40.0
MAX_UPPER_CUTOFF_C = 50.0
MAX_TARGET_GDD = 20_000.0
ANALOG_YEAR_RANGE = (1900, 2200)


def _number(value: Any, name: str, limit: float | None = None) -> float:
    # JSON numbers only, as in the rest of the registry: no strings, booleans or non-finite values.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_must_be_a_finite_number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name}_must_be_a_finite_number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name}_must_be_a_finite_number")
    if limit is not None and abs(number) > limit:
        raise ValueError(f"{name}_out_of_range")
    return number


def _population(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_must_be_an_integer")
    if value > MAX_POPULATION_UNITS:
        raise ValueError(f"{name}_out_of_range")
    return value


def _day(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{name}_must_be_an_iso_date") from None


def _weather(rows: Any, name: str, limit: int) -> list[est.WeatherDay]:
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError(f"{name}_must_be_a_list_of_at_most_{limit}_days")
    days = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{name}_rows_must_be_objects")
        days.append(est.WeatherDay(_day(row.get("date"), f"{name}.date"), _number(row.get("tmax_c"), f"{name}.tmax_c"),
                                   _number(row.get("tmin_c"), f"{name}.tmin_c")))
    return days


def _estimate(value: Any, name: str) -> est.Estimate | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{name}_must_be_an_object_with_value_and_standard_error")
    return est.Estimate(_number(value.get("value"), f"{name}.value", MAX_ESTIMATE_INPUT),
                        _number(value.get("standard_error"), f"{name}.standard_error", MAX_ESTIMATE_INPUT))


def _analog_year(key: Any) -> int:
    try:
        year = int(str(key))
    except ValueError:
        raise ValueError("analog_years_keys_must_be_years") from None
    if not ANALOG_YEAR_RANGE[0] <= year <= ANALOG_YEAR_RANGE[1]:
        raise ValueError("analog_years_outside_1900_to_2200")
    return year


def _finite_output(result: dict[str, Any]) -> dict[str, Any]:
    # Defence in depth: a non-finite number cannot be serialized as JSON (the response would fail).
    if not est._all_finite(result):
        raise ValueError("outputs_outside_numeric_range")
    return result


def _harvest_window(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    analog = inputs.get("analog_years") or {}
    if not isinstance(analog, dict) or len(analog) > MAX_ANALOG_YEARS:
        raise ValueError(f"analog_years_must_map_at_most_{MAX_ANALOG_YEARS}_years_to_daily_weather")
    analog_years = {_analog_year(year): rows for year, rows in analog.items()}
    base = _number(inputs["base_c"], "base_c", MAX_BASE_C)
    if base < -10:
        raise ValueError("base_c_out_of_range")
    upper = inputs.get("upper_cutoff_c")
    if upper is not None and not 0 <= _number(upper, "upper_cutoff_c", MAX_UPPER_CUTOFF_C):
        raise ValueError("upper_cutoff_c_out_of_range")
    request = est.HarvestWindowRequest(
        biofix=_day(inputs["biofix"], "biofix"), biofix_type=str(inputs.get("biofix_type") or "other")[:40],
        as_of=_day(inputs["as_of"], "as_of"),
        config=est.DegreeDayConfig(str(inputs["degree_day_method"]), base,
                                   None if upper is None else _number(upper, "upper_cutoff_c", MAX_UPPER_CUTOFF_C)),
        target=est.MaturityTarget(_number(inputs["target_low_gdd"], "target_low_gdd", MAX_TARGET_GDD),
                                  _number(inputs["target_high_gdd"], "target_high_gdd", MAX_TARGET_GDD),
                                  str(inputs["target_source"])[:500], str(inputs["target_source_type"])[:40],
                                  str(inputs.get("variety") or "")[:120] or None),
        observed=_weather(inputs["observed_weather"], "observed_weather", MAX_WEATHER_DAYS),
        analog_years={year: _weather(rows, f"analog_years.{year}", 366) for year, rows in analog_years.items()},
        observed_source=str(inputs.get("observed_source") or "")[:500] or None,
        analog_source=str(inputs.get("analog_source") or "")[:500] or None,
    )
    result = _finite_output(est.estimate_harvest_window(request))
    if result["status"] == "insufficient_evidence":
        raise ValueError(";".join(result.get("reasons") or ["insufficient_evidence"])[:1000])
    return result, {"biofix": request.biofix.isoformat(), "as_of": request.as_of.isoformat(),
                    "observed_days": len(request.observed), "analog_years": sorted(request.analog_years)}


def _strata(value: Any) -> list[est.Stratum] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_STRATA:
        raise ValueError(f"strata_must_be_a_list_of_at_most_{MAX_STRATA}_strata")
    strata = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("sample_counts"), list):
            raise ValueError("strata_need_stratum_id_population_units_and_sample_counts")
        population = _population(item.get("population_units"), "stratum_population_units")
        if len(item["sample_counts"]) > MAX_SAMPLE_UNITS:
            raise ValueError(f"stratum_sample_counts_must_have_at_most_{MAX_SAMPLE_UNITS}_counts")
        strata.append(est.Stratum(str(item.get("stratum_id") or "")[:200], population,
                                  [_number(count, "strata.sample_counts", MAX_COUNT_PER_UNIT) for count in item["sample_counts"]]))
    return strata


def _production(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    counts = inputs.get("sample_counts") or []
    if not isinstance(counts, list) or len(counts) > MAX_SAMPLE_UNITS:
        raise ValueError(f"sample_counts_must_be_a_list_of_at_most_{MAX_SAMPLE_UNITS}_counts")
    strata = _strata(inputs.get("strata"))
    area = inputs.get("area_hectares")
    area_value = None if area is None else Decimal(str(_number(area, "area_hectares")))
    population = _population(inputs["population_units"], "population_units")
    result = _finite_output(est.estimate_production(est.ProductionRequest(
        unit=str(inputs["unit"])[:40], object_label=str(inputs["object_label"])[:60], design=str(inputs["design"])[:60],
        population_units=population, sample_counts=[_number(value, "sample_counts", MAX_COUNT_PER_UNIT) for value in counts],
        count_source=str(inputs["count_source"])[:60],
        detection_rate=_estimate(inputs.get("detection_rate"), "detection_rate"),
        unit_weight_kg=_estimate(inputs.get("unit_weight_kg"), "unit_weight_kg"),
        marketable_fraction=_estimate(inputs.get("marketable_fraction"), "marketable_fraction"),
        area_hectares=area_value, detector_validation_id=inputs.get("detector_validation_id"), strata=strata,
    )))
    if result["status"] == "not_estimable":
        raise ValueError(";".join(result.get("reasons") or ["not_estimable"])[:1000])
    return result, {"sampled_units": result["sampled_units"], "population_units": population,
                    "strata": None if strata is None else len(strata)}


def _stage_proportions(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = resolve_profile(inputs.get("crop"))
    if profile is None:
        raise ValueError("crop_profile_not_supported")
    samples = inputs["samples"]
    if not isinstance(samples, list) or len(samples) > MAX_SAMPLE_UNITS:
        raise ValueError(f"samples_must_be_a_list_of_at_most_{MAX_SAMPLE_UNITS}_units")
    parsed = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict) or not isinstance(sample.get("counts"), dict):
            raise ValueError("samples_need_unit_id_and_counts")
        parsed.append(est.StageSample(str(sample.get("unit_id") or index)[:200],
                                      {str(stage): _number(value, f"samples.{stage}", MAX_COUNT_PER_UNIT)
                                       for stage, value in sample["counts"].items()}))
    rule = None
    readiness = inputs.get("readiness")
    if readiness is not None:
        if not isinstance(readiness, dict) or not isinstance(readiness.get("ready_stages"), list):
            raise ValueError("readiness_needs_ready_stages_threshold_share_and_source")
        rule = est.ReadinessRule(tuple(str(stage) for stage in readiness["ready_stages"]),
                                 _number(readiness.get("threshold_share"), "readiness.threshold_share"), str(readiness.get("source") or ""))
    population = inputs.get("population_units")
    if population is not None:
        population = _population(population, "population_units")
    result = _finite_output(est.estimate_stage_proportions(est.StageProportionRequest(
        crop_id=profile.crop_id, design=str(inputs["design"])[:60], samples=parsed, count_source=str(inputs["count_source"])[:60],
        detector_validation_id=inputs.get("detector_validation_id"), population_units=population, readiness=rule,
    )))
    if result["status"] == "not_estimable":
        raise ValueError(";".join(result.get("reasons") or ["not_estimable"])[:1000])
    return result, {"crop_id": profile.crop_id, "sampled_units": len(parsed)}


def register_crop_tools(register: Callable[..., None]) -> None:
    register(
        tool_id="crop.harvest_window.analog_years.v1", domain="phenology",
        description="Project a harvest window from accumulated degree days, a sourced maturity target range and analog weather seasons.",
        required_inputs=["biofix", "as_of", "degree_day_method", "base_c", "target_low_gdd", "target_high_gdd",
                         "target_source", "target_source_type", "observed_weather", "observed_source", "analog_years", "analog_source"],
        optional_inputs=["biofix_type", "upper_cutoff_c", "variety"],
        expected_units={"base_c": "degC", "upper_cutoff_c": "degC", "target_low_gdd": "degC-days", "target_high_gdd": "degC-days",
                        "observed_weather": "list of {date, tmax_c, tmin_c}", "analog_years": "{year: list of {date, tmax_c, tmin_c}}"},
        valid_ranges={"degree_day_method": "simple_average or modified_average_86_50", "target_source_type": "supplier_published, grower_historical or fitted_model",
                      "observed_weather": "complete daily series from biofix to as_of", "analog_years": "at least 5 valid seasons before the as-of year"},
        output_schema={"status": "projected | within_target_range | past_target_range", "window": "earliest/latest dates", "accumulated_gdd": "number"},
        calculation_method="Accumulate degree days to the as-of date, then the 10th percentile of dates reaching the target low and the 90th percentile of dates reaching the target high across analog seasons.",
        runner=_harvest_window,
        limitations=["The maturity target must come from a seed supplier, grower history or a fitted model; none is inferred.",
                     "Projected dates assume future temperatures resemble the analog seasons; the result is a window, not a date."],
    )
    register(
        tool_id="crop.production.sampling_estimate.v1", domain="yield_estimation",
        description="Estimate block production from a probability sample of units with visibility and unit-weight calibration.",
        required_inputs=["unit", "object_label", "design", "population_units", "count_source"],
        optional_inputs=["sample_counts", "strata", "detection_rate", "unit_weight_kg", "marketable_fraction", "area_hectares",
                         "detector_validation_id"],
        expected_units={"sample_counts": "objects per sampled unit", "strata": "list of {stratum_id, population_units, sample_counts}",
                        "unit_weight_kg": "kg per object", "area_hectares": "ha"},
        valid_ranges={"design": "simple_random, systematic_random_start or stratified_random", "count_source": "manual_count, or validated_detector with a detector_validation_id in the server registry",
                      "sample_counts": "at least 5 finite non-negative counts (unstratified designs)",
                      "strata": "required for stratified_random: at least 2 strata, each with its population and at least 2 counts; populations sum to population_units"},
        output_schema={"status": "estimated | count_only | density_only", "expected_production_kg": "value and 95% interval",
                       "variance_method": "simple_random_fpc | stratified_expansion_satterthwaite_df"},
        calculation_method="Expansion estimator with finite population correction; stratified designs use the population-weighted stratified mean with Satterthwaite degrees of freedom; relative errors of calibration factors combined in quadrature; Student t interval.",
        runner=_production,
        limitations=["Convenience samples are not extrapolated.", "Inputs are user-supplied and unverified unless counts come from a registry-verified detector."],
    )
    register(
        tool_id="crop.maturity.stage_proportions.v1", domain="phenology",
        description="Share of sampled objects at each maturity stage (for example almond hull split) with an optional readiness call against a sourced threshold.",
        required_inputs=["crop", "design", "samples", "count_source"],
        optional_inputs=["readiness", "population_units", "detector_validation_id"],
        expected_units={"samples": "list of {unit_id, counts: {stage: objects}}", "readiness.threshold_share": "fraction"},
        valid_ranges={"samples": "at least 5 units with objects; stages from the crop profile's maturity scale",
                      "count_source": "manual_count, or validated_detector with a detector_validation_id in the server registry"},
        output_schema={"stage_shares": "share and 95% interval per stage", "readiness": "ready | not_ready | uncertain | not_assessed"},
        calculation_method="Ratio estimator with sampled units as clusters; Student t interval; readiness compares the interval with the threshold.",
        runner=_stage_proportions,
        limitations=["Without an unstratified probability sample, shares describe only the sampled units and no readiness call is made; "
                     "stratified samples need stratum population weights, which this tool does not take.",
                     "The readiness threshold must come from the grower, an adviser or published guidance."],
    )

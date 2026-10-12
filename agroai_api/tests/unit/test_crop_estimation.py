"""Crop Intelligence estimators: degree days, harvest windows, production.

Weather series and counts here are constructed test inputs with hand-computed
expectations; they are not agronomic results.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import crop_estimation as est

MODIFIED = est.DegreeDayConfig("modified_average_86_50", 10.0, 30.0)
SIMPLE = est.DegreeDayConfig("simple_average", 10.0)


def _series(start: date, days: int, tmax: float, tmin: float = 10.0) -> list[est.WeatherDay]:
    return [est.WeatherDay(start + timedelta(days=offset), tmax, tmin) for offset in range(days)]


def _analog_year(year: int, tmax: float) -> list[est.WeatherDay]:
    return _series(date(year, 1, 1), 366 if year % 4 == 0 else 365, tmax)


# ---------------------------------------------------------------------------
# Degree days
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("tmax", "tmin", "config", "expected"),
    [
        (35, 15, MODIFIED, 12.5),   # Tmax capped at 30
        (8, 2, MODIFIED, 0.0),      # both raised to base
        (25, 5, MODIFIED, 7.5),     # Tmin raised to base
        (40, 32, MODIFIED, 20.0),   # both capped at the upper threshold
        (25, 5, SIMPLE, 5.0),
        (5, 0, SIMPLE, 0.0),
    ],
)
def test_daily_degree_days(tmax, tmin, config, expected):
    assert est.daily_degree_days(tmax, tmin, config) == pytest.approx(expected)


def test_degree_day_config_validation():
    assert est.DegreeDayConfig("modified_average_86_50", 10.0, None).validate() == ["degree_day_upper_cutoff_required_above_base"]
    assert est.DegreeDayConfig("magic", 10.0).validate() == ["degree_day_method_not_supported:magic"]
    assert MODIFIED.validate() == [] and SIMPLE.validate() == []


def test_weather_validation_reports_every_problem():
    start = date(2026, 4, 1)
    days = _series(start, 5, 25)
    days[1] = est.WeatherDay(days[1].day, 5, 20)            # tmax < tmin
    days.append(est.WeatherDay(days[2].day, 25, 10))         # duplicate
    days[3] = est.WeatherDay(days[3].day, float("nan"), 10)  # non-finite
    days[4] = est.WeatherDay(days[4].day, 75, 10)            # implausible
    usable, problems = est.validate_weather(days, start, start + timedelta(days=4))
    assert len(usable) == 2
    joined = " ".join(problems)
    for expected in ("tmax_below_tmin", "duplicate_weather_day", "non_finite_temperature", "implausible_temperature", "weather_series_missing_days:3"):
        assert expected in joined


def test_t_critical_values():
    assert est.t_critical_95(4) == 2.776
    assert est.t_critical_95(35) == pytest.approx(2.030, abs=1e-3)
    assert est.t_critical_95(500) == 1.960
    with pytest.raises(ValueError):
        est.t_critical_95(0)


# ---------------------------------------------------------------------------
# Harvest window
# ---------------------------------------------------------------------------

BIOFIX = date(2026, 4, 1)
AS_OF = date(2026, 4, 30)
OBSERVED = _series(BIOFIX, 30, 30)  # 10 degree days/day under the modified method -> 300


def _target(**overrides):
    values = {"low_gdd": 1000, "high_gdd": 1200, "source": "Seed supplier hybrid sheet (test)", "source_type": "supplier_published"}
    values.update(overrides)
    return est.MaturityTarget(**values)


def _request(**overrides):
    values = {
        "biofix": BIOFIX, "biofix_type": "planting", "as_of": AS_OF, "config": MODIFIED, "target": _target(),
        "observed": OBSERVED, "analog_years": {year: _analog_year(year, 30) for year in range(2019, 2024)}, "crop_id": "corn",
        "observed_source": "test station 1", "analog_source": "test station 1 history",
    }
    values.update(overrides)
    return est.HarvestWindowRequest(**values)


def test_constant_weather_gives_exact_window():
    result = est.estimate_harvest_window(_request())
    assert result["status"] == "projected"
    assert result["accumulated_gdd"] == 300.0
    assert result["progress_to_target_low"] == 0.3
    # 700 more degree days at 10/day -> 70 days; 900 -> 90 days.
    assert result["window"]["earliest"] == "2026-07-09"
    assert result["window"]["latest"] == "2026-07-29"
    assert result["analog_years_used"] == 5
    assert result["calibration_status"] == "uncalibrated_for_this_field"


def test_variable_analog_years_widen_the_window():
    analogs = {2019 + i: _analog_year(2019 + i, tmax) for i, tmax in enumerate((22, 24, 26, 28, 30))}  # 6..10 GDD/day
    window = est.estimate_harvest_window(_request(analog_years=analogs))["window"]
    # target-low offsets [70, 78, 88, 100, 117] -> p10 = 73.2; target-high [90, 100, 113, 129, 150] -> p90 = 141.6
    assert window["earliest"] == (AS_OF + timedelta(days=73)).isoformat()
    assert window["latest"] == (AS_OF + timedelta(days=142)).isoformat()
    assert window["median_entry"] == (AS_OF + timedelta(days=88)).isoformat()
    assert window["median_exit"] == (AS_OF + timedelta(days=113)).isoformat()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"target": None}, "maturity_target_required_from_supplier_grower_or_calibration"),
        ({"target": _target(source_type="guess")}, "maturity_target_source_type_not_accepted"),
        ({"target": _target(source=" ")}, "maturity_target_source_missing"),
        ({"target": _target(low_gdd=1300)}, "maturity_target_range_invalid"),
        ({"observed": OBSERVED[:10] + OBSERVED[11:]}, "weather_series_missing_days:1"),
        ({"as_of": date(2026, 3, 1)}, "as_of_before_biofix"),
        ({"config": est.DegreeDayConfig("modified_average_86_50", 10.0, 5.0)}, "degree_day_upper_cutoff_required_above_base"),
    ],
)
def test_harvest_window_refuses_without_evidence(overrides, reason):
    result = est.estimate_harvest_window(_request(**overrides))
    assert result["status"] == "insufficient_evidence"
    assert result["window"] is None
    assert reason in result["reasons"]


def test_too_few_analog_years_is_insufficient():
    result = est.estimate_harvest_window(_request(analog_years={year: _analog_year(year, 30) for year in range(2020, 2024)}))
    assert result["status"] == "insufficient_evidence"
    assert result["reasons"] == ["analog_years_usable:4<5"]


def test_analog_year_with_gap_is_unusable_not_guessed():
    analogs = {year: _analog_year(year, 30) for year in range(2018, 2024)}
    analogs[2018] = [day for day in analogs[2018] if day.day != date(2018, 6, 1)]
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert result["analog_years_unusable"] == [2018]
    assert result["analog_years_used"] == 5


def test_within_and_past_target_range():
    within = est.estimate_harvest_window(_request(target=_target(low_gdd=250, high_gdd=400)))
    assert within["status"] == "within_target_range"
    assert within["window"]["earliest"] == AS_OF.isoformat()
    past = est.estimate_harvest_window(_request(target=_target(low_gdd=100, high_gdd=200)))
    assert past["status"] == "past_target_range" and past["window"] is None


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------

def _production(**overrides):
    values = {
        "unit": "vine", "object_label": "cluster", "design": "systematic_random_start", "population_units": 100,
        "sample_counts": [10, 12, 8, 11, 9], "count_source": "manual_count",
        "detection_rate": est.Estimate(0.8, 0.04), "unit_weight_kg": est.Estimate(0.15, 0.0075),
        "area_hectares": Decimal("0.5"),
    }
    values.update(overrides)
    return est.ProductionRequest(**values)


def test_production_estimate_separates_counted_density_extrapolated_and_production():
    result = est.estimate_production(_production())
    assert result["status"] == "estimated"
    assert result["directly_counted_objects"] == 50
    density = result["visible_density_per_unit"]
    assert density["value"] == 10.0
    assert density["standard_error"] == pytest.approx(0.6892, abs=1e-4)          # sqrt(2.5/5 * 0.95)
    assert density["interval_95"] == pytest.approx([8.0868, 11.9132], abs=1e-3)   # t(4) = 2.776
    assert result["extrapolated_visible_objects"]["value"] == 1000.0
    assert result["estimated_total_objects"]["value"] == 1250.0
    assert result["estimated_total_objects"]["interval_95"] == pytest.approx([954.5, 1545.5], abs=0.2)
    production = result["expected_production_kg"]
    assert production["value"] == 187.5
    assert production["relative_standard_error"] == pytest.approx(0.0987, abs=1e-4)
    assert production["interval_95"] == pytest.approx([136.1, 238.9], abs=0.2)
    assert result["expected_production_kg_per_hectare"] == "375.00"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"design": "convenience_walk"}, "non_probability_sample_cannot_be_extrapolated"),
        ({"count_source": "unvalidated_detector"}, "counts_must_be_manual_or_from_a_validated_detector"),
        ({"count_source": "validated_detector"}, "validated_detector_requires_validation_reference"),
        ({"sample_counts": [10, 12, 8, 11]}, "sample_units:4<5"),
        ({"population_units": 3}, "population_units_must_be_known_and_at_least_the_sample"),
        ({"sample_counts": [10, -1, 8, 11, 9]}, "sample_counts_must_be_finite_and_non_negative"),
        ({"detection_rate": est.Estimate(1.4, 0.1)}, "detection_rate_above_one"),
    ],
)
def test_production_refuses_unsupported_extrapolation(overrides, reason):
    result = est.estimate_production(_production(**overrides))
    assert result["status"] == "not_estimable"
    assert reason in result["reasons"]
    assert "expected_production_kg" not in result


def test_missing_calibration_stops_at_the_supported_level():
    density_only = est.estimate_production(_production(detection_rate=None))
    assert density_only["status"] == "density_only"
    assert "estimated_total_objects" not in density_only
    assert density_only["missing_calibration"] == ["detection_rate_from_paired_hand_counts"]
    count_only = est.estimate_production(_production(unit_weight_kg=None))
    assert count_only["status"] == "count_only"
    assert "expected_production_kg" not in count_only


def test_marketable_fraction():
    result = est.estimate_production(_production(marketable_fraction=est.Estimate(0.9, 0.02)))
    assert result["status"] == "estimated"
    assert result["expected_marketable_kg"]["value"] == pytest.approx(168.75, abs=0.1)


def test_self_attested_detector_validation_is_not_trusted():
    """Audit finding 5: a client-supplied validation id is not proof."""
    result = est.estimate_production(_production(count_source="validated_detector", detector_validation_id="eval-2026-grape-v1"))
    assert result["status"] == "not_estimable"
    assert "detector_evaluation_not_in_server_registry" in result["reasons"]


def test_registry_verified_detector_counts_are_accepted_and_labelled(monkeypatch):
    from app.services import crop_model_registry as registry

    monkeypatch.setattr(registry, "VERIFIED_EVALUATIONS", (registry.VerifiedEvaluation(
        evaluation_id="eval-test-grape", model_id="rtdetr-grape-test", model_version="0.0-test", crop_id="wine_grape",
        dataset="test-holdout", split_policy="grouped by grower/site/season", report_ref="evals/reports/test.md",
        reviewed_by="test reviewer",
    ),))
    result = est.estimate_production(_production(count_source="validated_detector", detector_validation_id="eval-test-grape"))
    assert result["status"] == "estimated"
    assert result["input_provenance"]["sample_counts"] == "registry_verified_detector:eval-test-grape"
    assert result["input_provenance"]["calibration"] == "user_supplied_unverified"
    assert result["detector_evaluation"]["report_ref"] == "evals/reports/test.md"


def test_manual_inputs_are_labelled_user_supplied_unverified():
    result = est.estimate_production(_production())
    assert result["input_provenance"] == {
        "sample_counts": "user_supplied_unverified", "calibration": "user_supplied_unverified",
        "population_units": "user_supplied_unverified",
    }
    proposal = est.market_yield_proposal(result, estimate_id="est-x")
    assert "unverified" in proposal["note"] and proposal["apply_to_production"] is False


def test_market_yield_proposal_never_applies_itself():
    estimate = est.estimate_production(_production())
    proposal = est.market_yield_proposal(estimate, estimate_id="est-test-1")
    assert proposal["apply_to_production"] is False
    assert proposal["source"] == "crop_intelligence"
    assert proposal["yield_per_area"] == "375.00" and proposal["quantity_unit"] == "kg"
    assert "Review before applying" in proposal["note"]
    assert est.market_yield_proposal(est.estimate_production(_production(detection_rate=None)), estimate_id="x") is None


def test_harvest_suggestions_only_near_a_supported_window():
    result = est.estimate_harvest_window(_request())  # earliest 2026-07-09
    assert est.harvest_action_suggestions(result, date(2026, 5, 1)) == []  # more than 30 days away
    near = est.harvest_action_suggestions(result, date(2026, 6, 20))
    assert [item["action_code"] for item in near] == list(est.HARVEST_ACTION_CODES)
    assert all(item["requires_approval"] and not item["creates_task"] for item in near)
    assert near[0]["due_by"] == "2026-07-02"
    late = est.harvest_action_suggestions(result, date(2026, 7, 6))
    assert late[0]["due_by"] == "2026-07-06"  # never due in the past
    insufficient = est.estimate_harvest_window(_request(target=None))
    assert est.harvest_action_suggestions(insufficient, date(2026, 7, 1)) == []


# ---------------------------------------------------------------------------
# Non-finite inputs (audit finding 2)
# ---------------------------------------------------------------------------

NONFINITE = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("bad", NONFINITE)
@pytest.mark.parametrize("field", ["detection_rate", "unit_weight_kg", "marketable_fraction"])
@pytest.mark.parametrize("part", ["value", "standard_error"])
def test_nonfinite_calibration_inputs_are_rejected(bad, field, part):
    good = {"detection_rate": est.Estimate(0.8, 0.04), "unit_weight_kg": est.Estimate(0.15, 0.0075),
            "marketable_fraction": est.Estimate(0.9, 0.02)}[field]
    broken = est.Estimate(bad, good.standard_error) if part == "value" else est.Estimate(good.value, bad)
    overrides = {"marketable_fraction": est.Estimate(0.9, 0.02), field: broken}
    result = est.estimate_production(_production(**overrides))
    assert result["status"] == "not_estimable"
    assert f"{field}_invalid" in result["reasons"]
    assert "expected_production_kg" not in result


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_sample_counts_are_rejected(bad):
    result = est.estimate_production(_production(sample_counts=[10, 12, bad, 11, 9]))
    assert result["status"] == "not_estimable"
    assert "sample_counts_must_be_finite_and_non_negative" in result["reasons"]


@pytest.mark.parametrize("area", [Decimal("NaN"), Decimal("Infinity"), Decimal("0"), Decimal("-1")])
def test_invalid_area_is_rejected(area):
    result = est.estimate_production(_production(area_hectares=area))
    assert result["status"] == "not_estimable" and "area_hectares_invalid" in result["reasons"]


def test_estimates_never_contain_nonfinite_numbers():
    import json
    result = est.estimate_production(_production(marketable_fraction=est.Estimate(0.9, 0.02)))
    json.dumps(result, allow_nan=False)  # raises ValueError on NaN/Infinity anywhere in the payload


@pytest.mark.parametrize("bad", NONFINITE)
def test_nonfinite_degree_day_and_target_inputs_are_insufficient(bad):
    assert est.estimate_harvest_window(_request(config=est.DegreeDayConfig("modified_average_86_50", bad, 30.0)))["status"] == "insufficient_evidence"
    assert est.estimate_harvest_window(_request(config=est.DegreeDayConfig("modified_average_86_50", 10.0, bad)))["status"] == "insufficient_evidence"
    assert est.estimate_harvest_window(_request(target=_target(low_gdd=bad)))["status"] == "insufficient_evidence"



# ---------------------------------------------------------------------------
# Analog-season validation (audit finding 3)
# ---------------------------------------------------------------------------

def _good_analogs():
    return {year: _analog_year(year, 30) for year in range(2017, 2024)}  # 7 seasons, 2 spare


def _rejected(result, year):
    return next(item["reasons"] for item in result["analog_years_rejected"] if item["year"] == year)


def test_analog_duplicates_are_rejected_not_overridden():
    analogs = _good_analogs()
    analogs[2017] = [*analogs[2017], est.WeatherDay(date(2017, 6, 1), 45, 30)]  # second, conflicting 1 June
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert any(reason.startswith("duplicate_weather_day:2017-06-01") for reason in _rejected(result, 2017))
    assert result["analog_years_used"] == 6


def test_mislabeled_analog_year_is_rejected():
    analogs = _good_analogs()
    analogs[2018] = _analog_year(2012, 30)  # 2012 dates filed under 2018
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert _rejected(result, 2018)[0].startswith("analog_year_mislabeled:2012-")


def test_analog_tmax_below_tmin_and_nonfinite_are_rejected():
    analogs = _good_analogs()
    analogs[2017] = [est.WeatherDay(day.day, 5, 25) for day in analogs[2017]]
    analogs[2018] = [est.WeatherDay(day.day, float("nan") if day.day == date(2018, 7, 1) else 30, 10) for day in analogs[2018]]
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert _rejected(result, 2017)[0].startswith("tmax_below_tmin:")
    assert _rejected(result, 2018) == ["non_finite_temperature:2018-07-01"]
    assert result["analog_years_used"] == 5 and result["status"] == "projected"


def test_audit_reproduction_no_longer_uses_invalid_seasons():
    analogs = {year: _analog_year(year, 30) for year in range(2019, 2023)}
    analogs[2023] = [est.WeatherDay(day.day, 5, 25) for day in _analog_year(2023, 30)]
    analogs[2024] = _analog_year(2018, 30)
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert result["status"] == "insufficient_evidence"
    assert result["reasons"] == ["analog_years_usable:4<5"]
    assert {item["year"] for item in result["analog_years_rejected"]} == {2023, 2024}


def test_analog_year_must_precede_the_current_season():
    analogs = {**_good_analogs(), 2026: _analog_year(2026, 30)}
    result = est.estimate_harvest_window(_request(analog_years=analogs))
    assert _rejected(result, 2026) == ["analog_year_not_before_as_of_season"]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [({"observed_source": None}, "observed_weather_source_required"),
     ({"analog_source": " "}, "analog_weather_source_required")],
)
def test_weather_source_identity_is_required(overrides, reason):
    result = est.estimate_harvest_window(_request(**overrides))
    assert result["status"] == "insufficient_evidence" and reason in result["reasons"]


def test_season_crossing_new_year_uses_the_following_january():
    def season(year):
        # Cold January/February of the *same* calendar year (before the season) must be ignored;
        # the season itself runs 1 Nov of `year` through 30 Apr of `year + 1` at 10 degree days/day.
        early = [est.WeatherDay(date(year, 1, 1) + timedelta(days=i), 5, 0) for i in range(59)]
        start = date(year, 11, 1)
        days = [est.WeatherDay(start + timedelta(days=i), 30, 10) for i in range((date(year + 1, 4, 30) - start).days + 1)]
        return early + days

    biofix, as_of = date(2026, 11, 1), date(2026, 11, 15)
    result = est.estimate_harvest_window(_request(
        biofix=biofix, as_of=as_of, observed=_series(biofix, 15, 30),
        target=_target(low_gdd=750, high_gdd=950), analog_years={year: season(year) for year in range(2019, 2024)},
    ))
    # 150 accumulated; 600 more at 10/day -> 60 days -> 14 Jan 2027; 800 more -> 80 days -> 3 Feb 2027.
    assert result["status"] == "projected"
    assert result["window"]["earliest"] == "2027-01-14"
    assert result["window"]["latest"] == "2027-02-03"


# ---------------------------------------------------------------------------
# Maturity stage proportions (almond hull split as the first use case)
# ---------------------------------------------------------------------------

def _trees(splits=(2, 4, 6, 3, 5), per_tree=10):
    return [est.StageSample(f"tree-{i}", {"hull_split": s, "hull_intact": per_tree - s}) for i, s in enumerate(splits)]


def _stages(**overrides):
    values = {"crop_id": "almond", "design": "simple_random", "samples": _trees(), "count_source": "manual_count"}
    values.update(overrides)
    return est.StageProportionRequest(**values)


def test_hull_split_share_and_cluster_interval():
    result = est.estimate_stage_proportions(_stages())
    assert result["status"] == "estimated" and result["scope"] == "block_estimate"
    split = result["stage_shares"]["hull_split"]
    # p = 20/50; residuals (-2, 0, 2, -1, 1) -> var = 2.5 / (5 * 10^2) -> se 0.0707; t(4) = 2.776
    assert split["share"] == 0.4
    assert split["interval_95"] == pytest.approx([0.2037, 0.5963], abs=1e-4)
    assert result["stage_shares"]["hull_open_dry"]["share"] == 0.0
    assert result["objects_observed"] == 50 and result["sampled_units"] == 5


def test_finite_population_correction_narrows_interval():
    wide = est.estimate_stage_proportions(_stages())["stage_shares"]["hull_split"]["interval_95"]
    narrow = est.estimate_stage_proportions(_stages(population_units=50))["stage_shares"]["hull_split"]["interval_95"]
    assert narrow[1] - narrow[0] == pytest.approx((wide[1] - wide[0]) * math.sqrt(0.9), abs=1e-3)


@pytest.mark.parametrize(("threshold", "status"), [(0.2, "ready"), (0.5, "uncertain"), (0.6, "not_ready")])
def test_readiness_uses_the_interval_not_the_point(threshold, status):
    rule = est.ReadinessRule(("hull_split", "hull_open_dry"), threshold, "Grower harvest plan (test)")
    readiness = est.estimate_stage_proportions(_stages(readiness=rule))["readiness"]
    assert readiness["status"] == status
    assert readiness["observed_share"] == 0.4 and readiness["threshold_source"] == "Grower harvest plan (test)"


def test_convenience_sample_describes_sampled_units_only():
    rule = est.ReadinessRule(("hull_split",), 0.2, "Grower harvest plan (test)")
    result = est.estimate_stage_proportions(_stages(design="edge_row_walk", readiness=rule))
    assert result["scope"] == "sampled_units_only"
    assert "interval_95" not in result["stage_shares"]["hull_split"]
    assert result["readiness"]["status"] == "not_assessed_non_probability_sample"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"samples": _trees((2, 4, 6, 3))}, "sample_units_with_objects:4<5"),
        ({"samples": [*_trees(), est.StageSample("x", {"ripe_cherry": 3})]}, "stages_not_in_almond_scale:ripe_cherry"),
        ({"samples": [*_trees()[:4], est.StageSample("x", {"hull_split": float("nan")})]}, "stage_counts_must_be_finite_and_non_negative"),
        ({"count_source": "validated_detector", "detector_validation_id": "trust-me"}, "detector_evaluation_not_in_server_registry"),
        ({"count_source": "guessed"}, "counts_must_be_manual_or_from_a_validated_detector"),
        ({"crop_id": "corn"}, "stages_not_in_corn_scale:hull_intact,hull_split"),
        ({"readiness": est.ReadinessRule(("hull_split",), 0.2, " ")}, "readiness_threshold_source_required"),
        ({"readiness": est.ReadinessRule(("ripe",), 0.2, "x")}, "readiness_stages_not_in_scale"),
        ({"readiness": est.ReadinessRule(("hull_split",), 1.5, "x")}, "readiness_threshold_must_be_a_share_in_(0,1]"),
    ],
)
def test_stage_proportions_refuse_unsupported_inputs(overrides, reason):
    result = est.estimate_stage_proportions(_stages(**overrides))
    assert result["status"] == "not_estimable"
    assert reason in result["reasons"]


# ---------------------------------------------------------------------------
# Stratified designs (second review): population-weighted, never pooled
# ---------------------------------------------------------------------------

def _strata(high=(10, 10, 10, 10, 10), low=(1, 1, 1, 1, 1)):
    return [est.Stratum("high-load", 10, list(high)), est.Stratum("low-load", 90, list(low))]


def _stratified(**overrides):
    values = {"design": "stratified_random", "population_units": 100, "sample_counts": [], "strata": _strata(),
              "detection_rate": None, "unit_weight_kg": None}
    values.update(overrides)
    return _production(**values)


def test_stratified_total_is_population_weighted_not_the_pooled_mean():
    """Reviewer's example: 10 trees at 10 fruit and 90 at 1, five sampled from each."""
    result = est.estimate_production(_stratified())
    assert result["status"] == "density_only"
    assert result["extrapolated_visible_objects"]["value"] == 190.0  # the pooled mean would give 550
    assert result["visible_density_per_unit"]["value"] == 1.9
    assert result["variance_method"] == "stratified_expansion_satterthwaite_df"
    assert [s["mean_visible_per_unit"] for s in result["strata"]] == [10.0, 1.0]


def test_stratified_variance_and_satterthwaite_degrees_of_freedom():
    # A: N=10, n=5, mean 10, s^2=2; B: N=90, n=5, mean 1, s^2=0.5.
    # Var(total) = 100*0.5*2/5 + 8100*(85/90)*0.5/5 = 20 + 765 = 785 -> SE 28.018.
    # df = 785^2 / (20^2/4 + 765^2/4) = 4.21 -> 4 (t = 2.776).
    result = est.estimate_production(_stratified(strata=_strata(high=(8, 10, 12, 10, 10), low=(0, 1, 2, 1, 1))))
    assert result["degrees_of_freedom"] == 4
    assert result["extrapolated_visible_objects"]["value"] == 190.0
    assert result["extrapolated_visible_objects"]["interval_95"] == pytest.approx([112.2, 267.8], abs=0.1)
    assert result["visible_density_per_unit"]["standard_error"] == pytest.approx(0.2802, abs=1e-4)


def test_stratified_estimate_carries_calibration_through():
    result = est.estimate_production(_stratified(detection_rate=est.Estimate(0.8, 0.04), unit_weight_kg=est.Estimate(0.15, 0.0075)))
    assert result["status"] == "estimated"
    assert result["estimated_total_objects"]["value"] == pytest.approx(237.5)
    assert result["expected_production_kg"]["value"] == pytest.approx(35.6, abs=0.1)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"strata": None, "sample_counts": [10, 12, 8, 11, 9]}, "stratified_random_requires_at_least_2_strata_with_population_and_samples"),
        ({"strata": _strata()[:1]}, "stratified_random_requires_at_least_2_strata_with_population_and_samples"),
        ({"sample_counts": [1, 2, 3]}, "stratified_random_uses_per_stratum_counts_not_pooled_sample_counts"),
        ({"population_units": 120}, "population_units_must_equal_the_sum_of_stratum_populations"),
        ({"strata": [est.Stratum("a", 10, [1, 2, 3]), est.Stratum("a", 90, [1, 2, 3])]}, "stratum_ids_must_be_present_and_unique"),
        ({"strata": [est.Stratum("a", 10, [1]), est.Stratum("b", 90, [1, 2, 3, 4])]}, "stratum_needs_at_least_2_sampled_units:a"),
        ({"strata": [est.Stratum("a", 2, [1, 2, 3]), est.Stratum("b", 98, [1, 2, 3])]}, "stratum_population_must_be_an_integer_at_least_its_sample:a"),
        ({"strata": [est.Stratum("a", 10, [1, float("nan"), 3]), est.Stratum("b", 90, [1, 2, 3])]}, "sample_counts_must_be_finite_and_non_negative"),
    ],
)
def test_stratified_design_without_valid_strata_fails_closed(overrides, reason):
    result = est.estimate_production(_stratified(**overrides))
    assert result["status"] == "not_estimable"
    assert reason in result["reasons"]
    assert len(result["reasons"]) == len(set(result["reasons"]))


def test_strata_are_refused_for_unstratified_designs():
    result = est.estimate_production(_production(strata=_strata()))
    assert result["status"] == "not_estimable"
    assert "strata_require_stratified_random_design" in result["reasons"]


def test_unstratified_designs_report_their_variance_method():
    assert est.estimate_production(_production())["variance_method"] == "simple_random_fpc_approximation_for_systematic_sample"
    assert est.estimate_production(_production(design="simple_random"))["variance_method"] == "simple_random_fpc"


def test_stratified_stage_shares_describe_sampled_units_only():
    rule = est.ReadinessRule(("hull_split",), 0.2, "Grower harvest plan (test)")
    result = est.estimate_stage_proportions(_stages(design="stratified_random", readiness=rule))
    assert result["scope"] == "sampled_units_only"
    assert result["scope_reason"] == "stratified_design_needs_stratum_population_weights"
    assert "interval_95" not in result["stage_shares"]["hull_split"]
    assert result["readiness"]["status"] == "not_assessed_stratified_without_stratum_weights"

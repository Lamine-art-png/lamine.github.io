"""Crop Intelligence estimators: degree days, harvest windows, production.

Weather series and counts here are constructed test inputs with hand-computed
expectations; they are not agronomic results.
"""
from __future__ import annotations

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
        ({"sample_counts": [10, -1, 8, 11, 9]}, "sample_counts_must_be_non_negative"),
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


def test_marketable_fraction_and_validated_detector():
    result = est.estimate_production(_production(
        count_source="validated_detector", detector_validation_id="eval-2026-grape-v1",
        marketable_fraction=est.Estimate(0.9, 0.02),
    ))
    assert result["status"] == "estimated"
    assert result["expected_marketable_kg"]["value"] == pytest.approx(168.75, abs=0.1)


def test_market_yield_proposal_never_applies_itself():
    estimate = est.estimate_production(_production())
    proposal = est.market_yield_proposal(estimate, estimate_id="est-test-1")
    assert proposal["apply_to_production"] is False
    assert proposal["source"] == "crop_intelligence"
    assert proposal["yield_per_area"] == "375.00" and proposal["quantity_unit"] == "kg"
    assert "Review before applying" in proposal["note"]
    assert est.market_yield_proposal(est.estimate_production(_production(detection_rate=None)), estimate_id="x") is None

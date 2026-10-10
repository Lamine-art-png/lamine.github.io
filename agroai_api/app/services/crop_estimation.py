"""Crop Intelligence estimation: degree days, harvest windows, production.

Every estimator here refuses to answer when the evidence cannot support an
answer, and says why. Nothing in this module invents a crop parameter:

- **Degree days** use an explicit method and thresholds and require a
  complete daily temperature series (no silent gap filling).
- **Harvest window** needs a degree-day target *range* to harvest maturity
  with a stated source (seed supplier, grower history, or a fitted model),
  a biofix date, observed weather up to the as-of date, and analog weather
  years to project the remaining accumulation. The output is a window with
  the spread across analog years, never an exact date.
- **Production** needs a probability sample (random, systematic with a
  random start, or stratified random) of a known population of units,
  counts from hand counting or a *validated* detector, and calibration for
  visibility and unit weight. Directly counted objects, estimated density,
  extrapolated totals and expected production are reported separately with
  intervals. A walk along the headland is a convenience sample and is not
  extrapolated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Sequence

ESTIMATION_VERSION = "crop-estimation/1"
DEGREE_DAY_METHODS = {"simple_average", "modified_average_86_50"}
TARGET_SOURCES = {"supplier_published", "grower_historical", "fitted_model"}
PROBABILITY_DESIGNS = {"simple_random", "systematic_random_start", "stratified_random"}
COUNT_SOURCES = {"manual_count", "validated_detector"}
MIN_ANALOG_YEARS = 5
MIN_SAMPLE_UNITS = 5
PLAUSIBLE_TEMPERATURE_C = (-60.0, 60.0)

# Two-sided 95% Student t critical values.
_T_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    40: 2.021, 60: 2.000, 120: 1.980,
}


def t_critical_95(df: int) -> float:
    if df < 1:
        raise ValueError("degrees of freedom must be >= 1")
    if df in _T_95:
        return _T_95[df]
    if df > 120:
        return 1.960
    keys = sorted(_T_95)
    upper = next(key for key in keys if key > df)
    lower = max(key for key in keys if key < df)
    # Interpolate in 1/df, which is close to linear for t quantiles.
    weight = (1 / df - 1 / upper) / (1 / lower - 1 / upper)
    return _T_95[upper] + weight * (_T_95[lower] - _T_95[upper])


# ---------------------------------------------------------------------------
# Degree days
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DegreeDayConfig:
    method: str
    base_c: float
    upper_cutoff_c: float | None = None

    def validate(self) -> list[str]:
        problems = []
        if self.method not in DEGREE_DAY_METHODS:
            problems.append(f"degree_day_method_not_supported:{self.method}")
        if not math.isfinite(self.base_c):
            problems.append("degree_day_base_not_finite")
        if self.method == "modified_average_86_50":
            if self.upper_cutoff_c is None or not math.isfinite(self.upper_cutoff_c) or self.upper_cutoff_c <= self.base_c:
                problems.append("degree_day_upper_cutoff_required_above_base")
        return problems


def daily_degree_days(tmax_c: float, tmin_c: float, config: DegreeDayConfig) -> float:
    if config.method == "simple_average":
        return max(0.0, (tmax_c + tmin_c) / 2 - config.base_c)
    upper = float(config.upper_cutoff_c)  # validated by DegreeDayConfig.validate
    high = min(max(tmax_c, config.base_c), upper)
    low = min(max(tmin_c, config.base_c), upper)
    return max(0.0, (high + low) / 2 - config.base_c)


@dataclass
class WeatherDay:
    day: date
    tmax_c: float
    tmin_c: float


def validate_weather(days: Sequence[WeatherDay], start: date, end: date) -> tuple[list[WeatherDay], list[str]]:
    """Return days in [start, end] in order, and any reasons they are unusable."""
    problems: list[str] = []
    by_day: dict[date, WeatherDay] = {}
    for item in days:
        if not (start <= item.day <= end):
            continue
        if item.day in by_day:
            problems.append(f"duplicate_weather_day:{item.day.isoformat()}")
            continue
        values = (item.tmax_c, item.tmin_c)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            problems.append(f"non_finite_temperature:{item.day.isoformat()}")
            continue
        if not all(PLAUSIBLE_TEMPERATURE_C[0] <= value <= PLAUSIBLE_TEMPERATURE_C[1] for value in values):
            problems.append(f"implausible_temperature:{item.day.isoformat()}")
            continue
        if item.tmax_c < item.tmin_c:
            problems.append(f"tmax_below_tmin:{item.day.isoformat()}")
            continue
        by_day[item.day] = item
    expected = (end - start).days + 1
    missing = expected - len(by_day)
    if missing > 0:
        problems.append(f"weather_series_missing_days:{missing}")
    return [by_day[day] for day in sorted(by_day)], problems


def accumulate(days: Iterable[WeatherDay], config: DegreeDayConfig) -> float:
    return sum(daily_degree_days(item.tmax_c, item.tmin_c, config) for item in days)


# ---------------------------------------------------------------------------
# Harvest window
# ---------------------------------------------------------------------------

@dataclass
class MaturityTarget:
    low_gdd: float
    high_gdd: float
    source: str
    source_type: str
    variety: str | None = None

    def validate(self) -> list[str]:
        problems = []
        if self.source_type not in TARGET_SOURCES:
            problems.append("maturity_target_source_type_not_accepted")
        if not str(self.source or "").strip():
            problems.append("maturity_target_source_missing")
        if not (math.isfinite(self.low_gdd) and math.isfinite(self.high_gdd)) or self.low_gdd <= 0 or self.high_gdd < self.low_gdd:
            problems.append("maturity_target_range_invalid")
        return problems


@dataclass
class HarvestWindowRequest:
    biofix: date
    biofix_type: str
    as_of: date
    config: DegreeDayConfig
    target: MaturityTarget | None
    observed: Sequence[WeatherDay]
    analog_years: dict[int, Sequence[WeatherDay]] = field(default_factory=dict)
    crop_id: str | None = None
    horizon_days: int = 240


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _days_to_reach(start: date, needed: float, analog: dict[tuple[int, int], WeatherDay], config: DegreeDayConfig, horizon: int) -> int | None:
    """Days after ``start`` until ``needed`` degree days accumulate using the
    analog year's weather for the same calendar days; ``None`` if not reached
    within the horizon or if the analog series has a gap."""
    if needed <= 0:
        return 0
    total = 0.0
    for offset in range(1, horizon + 1):
        current = start + timedelta(days=offset)
        key = (current.month, current.day)
        if key == (2, 29) and key not in analog:
            key = (2, 28)
        item = analog.get(key)
        if item is None:
            return None
        total += daily_degree_days(item.tmax_c, item.tmin_c, config)
        if total >= needed:
            return offset
    return None


def estimate_harvest_window(request: HarvestWindowRequest) -> dict[str, Any]:
    reasons: list[str] = list(request.config.validate())
    if request.target is None:
        reasons.append("maturity_target_required_from_supplier_grower_or_calibration")
    else:
        reasons.extend(request.target.validate())
    if request.as_of < request.biofix:
        reasons.append("as_of_before_biofix")
    observed, weather_problems = validate_weather(request.observed, request.biofix, request.as_of) if request.as_of >= request.biofix else ([], [])
    reasons.extend(weather_problems)

    base = {
        "estimation_version": ESTIMATION_VERSION,
        "crop_id": request.crop_id,
        "biofix": {"date": request.biofix.isoformat(), "type": request.biofix_type},
        "as_of": request.as_of.isoformat(),
        "degree_day_method": {"method": request.config.method, "base_c": request.config.base_c,
                              "upper_cutoff_c": request.config.upper_cutoff_c},
        "target": None if request.target is None else {
            "low_gdd": request.target.low_gdd, "high_gdd": request.target.high_gdd,
            "source": request.target.source, "source_type": request.target.source_type, "variety": request.target.variety,
        },
        "calibration_status": "uncalibrated_for_this_field",
        "weather_dependencies": [
            "Observed accumulation depends on the completeness and siting of the supplied weather series.",
            "Projected dates assume future temperatures resemble the analog years supplied.",
        ],
    }
    if reasons:
        return {**base, "status": "insufficient_evidence", "reasons": reasons, "window": None}

    target = request.target
    assert target is not None
    accumulated = accumulate(observed, request.config)
    base["accumulated_gdd"] = round(accumulated, 1)
    base["progress_to_target_low"] = round(min(accumulated / target.low_gdd, 9.99), 3)
    if accumulated >= target.high_gdd:
        return {**base, "status": "past_target_range", "reasons": [], "window": None}
    if accumulated >= target.low_gdd:
        status = "within_target_range"
    else:
        status = "projected"

    end_offsets: list[int] = []
    start_offsets: list[int] = []
    unusable: list[int] = []
    for year, series in sorted(request.analog_years.items()):
        analog = {(item.day.month, item.day.day): item for item in series}
        days_low = _days_to_reach(request.as_of, target.low_gdd - accumulated, analog, request.config, request.horizon_days)
        days_high = _days_to_reach(request.as_of, target.high_gdd - accumulated, analog, request.config, request.horizon_days)
        if days_low is None or days_high is None:
            unusable.append(year)
            continue
        start_offsets.append(days_low)
        end_offsets.append(days_high)
    if len(start_offsets) < MIN_ANALOG_YEARS:
        return {
            **base, "status": "insufficient_evidence", "window": None,
            "reasons": [f"analog_years_usable:{len(start_offsets)}<{MIN_ANALOG_YEARS}"],
            "analog_years_unusable": unusable,
        }
    earliest = request.as_of + timedelta(days=round(_percentile(start_offsets, 0.1)))
    latest = request.as_of + timedelta(days=round(_percentile(end_offsets, 0.9)))
    central_start = request.as_of + timedelta(days=round(_percentile(start_offsets, 0.5)))
    central_end = request.as_of + timedelta(days=round(_percentile(end_offsets, 0.5)))
    return {
        **base,
        "status": status,
        "reasons": [],
        "window": {
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
            "median_entry": central_start.isoformat(),
            "median_exit": central_end.isoformat(),
            "interval": f"10th percentile of target-low dates to 90th percentile of target-high dates across {len(start_offsets)} analog years",
        },
        "analog_years_used": len(start_offsets),
        "analog_years_unusable": unusable,
    }


# ---------------------------------------------------------------------------
# Production from a sampling design
# ---------------------------------------------------------------------------

@dataclass
class Estimate:
    value: float
    standard_error: float

    def interval(self, critical: float) -> tuple[float, float]:
        return max(0.0, self.value - critical * self.standard_error), self.value + critical * self.standard_error


@dataclass
class ProductionRequest:
    unit: str                                  # e.g. "vine", "tree", "row_meter"
    object_label: str                          # e.g. "cluster"
    design: str
    population_units: int                      # N: units in the block
    sample_counts: Sequence[float]             # visible count per sampled unit
    count_source: str
    detection_rate: Estimate | None = None     # visible / true objects, from paired hand counts
    unit_weight_kg: Estimate | None = None     # mass per object
    marketable_fraction: Estimate | None = None
    area_hectares: Decimal | None = None
    detector_validation_id: str | None = None


def _ratio_cv(estimate: Estimate | None) -> float:
    if estimate is None or estimate.value == 0:
        return 0.0
    return estimate.standard_error / estimate.value


def estimate_production(request: ProductionRequest) -> dict[str, Any]:
    """Expansion estimator with finite population correction.

    Total visible objects = N x mean visible per unit. Dividing by the
    detection (visibility) rate gives total objects; multiplying by unit
    weight gives production. Relative standard errors of independent factors
    combine in quadrature (delta method); the interval uses the Student t
    value for the sample's degrees of freedom.
    """
    reasons: list[str] = []
    counts = [float(value) for value in request.sample_counts]
    n = len(counts)
    if request.design not in PROBABILITY_DESIGNS:
        reasons.append("non_probability_sample_cannot_be_extrapolated")
    if request.count_source not in COUNT_SOURCES:
        reasons.append("counts_must_be_manual_or_from_a_validated_detector")
    if request.count_source == "validated_detector" and not request.detector_validation_id:
        reasons.append("validated_detector_requires_validation_reference")
    if n < MIN_SAMPLE_UNITS:
        reasons.append(f"sample_units:{n}<{MIN_SAMPLE_UNITS}")
    if request.population_units <= 0 or request.population_units < n:
        reasons.append("population_units_must_be_known_and_at_least_the_sample")
    if any(not math.isfinite(value) or value < 0 for value in counts):
        reasons.append("sample_counts_must_be_non_negative")
    for name, estimate in (("detection_rate", request.detection_rate), ("unit_weight_kg", request.unit_weight_kg),
                           ("marketable_fraction", request.marketable_fraction)):
        if estimate is not None and (estimate.value <= 0 or estimate.standard_error < 0):
            reasons.append(f"{name}_invalid")
    if request.detection_rate is not None and request.detection_rate.value > 1:
        reasons.append("detection_rate_above_one")
    if request.marketable_fraction is not None and request.marketable_fraction.value > 1:
        reasons.append("marketable_fraction_above_one")

    directly_counted = sum(counts) if counts else 0.0
    result: dict[str, Any] = {
        "estimation_version": ESTIMATION_VERSION,
        "unit": request.unit,
        "object_label": request.object_label,
        "design": request.design,
        "count_source": request.count_source,
        "sampled_units": n,
        "population_units": request.population_units,
        "directly_counted_objects": directly_counted,
        "calibration_status": "uncalibrated_for_this_field",
    }
    if reasons:
        return {**result, "status": "not_estimable", "reasons": reasons}

    mean = directly_counted / n
    variance = sum((value - mean) ** 2 for value in counts) / (n - 1)
    fpc = 1 - n / request.population_units
    mean_se = math.sqrt(variance / n * fpc)
    critical = t_critical_95(n - 1)
    density = Estimate(mean, mean_se)
    result["visible_density_per_unit"] = {
        "value": round(mean, 4), "standard_error": round(mean_se, 4),
        "interval_95": [round(bound, 4) for bound in density.interval(critical)],
    }
    visible_total = Estimate(request.population_units * mean, request.population_units * mean_se)
    result["extrapolated_visible_objects"] = {
        "value": round(visible_total.value, 1), "interval_95": [round(bound, 1) for bound in visible_total.interval(critical)],
    }
    missing: list[str] = []
    if request.detection_rate is None:
        missing.append("detection_rate_from_paired_hand_counts")
        result["status"] = "density_only"
        result["missing_calibration"] = missing
        return result

    cv_sample = mean_se / mean if mean else 0.0
    total_objects_value = visible_total.value / request.detection_rate.value
    cv_total = math.sqrt(cv_sample ** 2 + _ratio_cv(request.detection_rate) ** 2)
    total_objects = Estimate(total_objects_value, total_objects_value * cv_total)
    result["estimated_total_objects"] = {
        "value": round(total_objects.value, 1), "interval_95": [round(bound, 1) for bound in total_objects.interval(critical)],
    }
    if request.unit_weight_kg is None:
        missing.append("unit_weight_kg")
        result["status"] = "count_only"
        result["missing_calibration"] = missing
        return result

    production_value = total_objects.value * request.unit_weight_kg.value
    cv_production = math.sqrt(cv_total ** 2 + _ratio_cv(request.unit_weight_kg) ** 2)
    production = Estimate(production_value, production_value * cv_production)
    result["expected_production_kg"] = {
        "value": round(production.value, 1), "interval_95": [round(bound, 1) for bound in production.interval(critical)],
        "relative_standard_error": round(cv_production, 4),
    }
    if request.marketable_fraction is not None:
        marketable_value = production.value * request.marketable_fraction.value
        cv_marketable = math.sqrt(cv_production ** 2 + _ratio_cv(request.marketable_fraction) ** 2)
        marketable = Estimate(marketable_value, marketable_value * cv_marketable)
        result["expected_marketable_kg"] = {
            "value": round(marketable.value, 1), "interval_95": [round(bound, 1) for bound in marketable.interval(critical)],
        }
    if request.area_hectares and request.area_hectares > 0:
        per_hectare = Decimal(str(round(production.value, 6))) / request.area_hectares
        result["expected_production_kg_per_hectare"] = format(per_hectare.quantize(Decimal("0.01")), "f")
    result["status"] = "estimated"
    result["interval_method"] = "Student t on sampled units; relative errors of calibration factors combined in quadrature"
    return result


def market_yield_proposal(estimate: dict[str, Any], *, estimate_id: str) -> dict[str, Any] | None:
    """Turn an estimate into a *proposal* for the existing Market Intelligence
    yield-estimate intake. It never applies to expected production by itself:
    ``apply_to_production`` is false so the customer's current values stay in
    force until a person with write access reviews and applies it."""
    if estimate.get("status") != "estimated" or not estimate.get("expected_production_kg_per_hectare"):
        return None
    low, high = estimate["expected_production_kg"]["interval_95"]
    return {
        "yield_per_area": estimate["expected_production_kg_per_hectare"],
        "quantity_unit": "kg",
        "area_unit": "hectare",
        "source": "crop_intelligence",
        "apply_to_production": False,
        "note": (
            f"Crop Intelligence estimate {estimate_id} ({estimate.get('design')}, n={estimate.get('sampled_units')}, "
            f"{estimate.get('count_source')}); 95% interval for block production {low}–{high} kg. Review before applying."
        )[:1000],
    }

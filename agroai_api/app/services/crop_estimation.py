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
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Sequence

from app.services import crop_model_registry

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


# Projected windows run up to a year past as_of; dates are kept far from date.max.
MIN_SEASON_DATE = date(1900, 1, 1)
MAX_SEASON_DATE = date(2200, 12, 31)


def t_critical_95(df: int) -> float:
    if df < 1:
        raise ValueError("degrees of freedom must be >= 1")
    if df in _T_95:
        return _T_95[df]
    if df > 120:
        return 1.960 + (1.980 - 1.960) * 120 / df  # 1/df interpolation toward the normal value
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
    observed_source: str | None = None   # station or dataset identity for the observed series
    analog_source: str | None = None     # station or dataset identity for the analog seasons


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _same_day_in_year(day: date, year: int) -> date:
    try:
        return day.replace(year=year)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=year, day=28)


def validate_analog_season(year: int, series: Sequence[WeatherDay], as_of: date, horizon: int) -> tuple[dict[date, WeatherDay], list[str]]:
    """Validate one analog season and index it by real date.

    Analog season ``year`` starts on the as-of month/day in that year and may
    run into the following year (a season crossing New Year), so its days
    must fall in ``year`` or ``year + 1``. Any duplicate date, non-finite or
    implausible temperature, Tmax below Tmin, or day labelled with another
    year rejects the whole season rather than silently overriding values.
    """
    problems: list[str] = []
    by_date: dict[date, WeatherDay] = {}
    for item in series:
        if item.day.year not in (year, year + 1):
            problems.append(f"analog_year_mislabeled:{item.day.isoformat()}")
            continue
        if item.day in by_date:
            problems.append(f"duplicate_weather_day:{item.day.isoformat()}")
            continue
        values = (item.tmax_c, item.tmin_c)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values):
            problems.append(f"non_finite_temperature:{item.day.isoformat()}")
            continue
        if not all(PLAUSIBLE_TEMPERATURE_C[0] <= value <= PLAUSIBLE_TEMPERATURE_C[1] for value in values):
            problems.append(f"implausible_temperature:{item.day.isoformat()}")
            continue
        if item.tmax_c < item.tmin_c:
            problems.append(f"tmax_below_tmin:{item.day.isoformat()}")
            continue
        by_date[item.day] = item
    start = _same_day_in_year(as_of, year)
    if not problems and not any(start < day <= start + timedelta(days=horizon) for day in by_date):
        problems.append("analog_season_has_no_days_after_as_of")
    return by_date, problems[:20]


def _days_to_reach(start: date, needed: float, season: dict[date, WeatherDay], config: DegreeDayConfig, horizon: int) -> int | None:
    """Days after ``start`` until ``needed`` degree days accumulate using the
    analog season's real dates; ``None`` if not reached within the horizon
    or if the season has a gap before the target is reached."""
    if needed <= 0:
        return 0
    total = 0.0
    for offset in range(1, horizon + 1):
        item = season.get(start + timedelta(days=offset))
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
    if not (MIN_SEASON_DATE <= request.biofix <= MAX_SEASON_DATE and MIN_SEASON_DATE <= request.as_of <= MAX_SEASON_DATE):
        reasons.append("season_dates_outside_1900_to_2200")
    observed, weather_problems = validate_weather(request.observed, request.biofix, request.as_of) if request.as_of >= request.biofix else ([], [])
    reasons.extend(weather_problems)
    if not str(request.observed_source or "").strip():
        reasons.append("observed_weather_source_required")
    if request.analog_years and not str(request.analog_source or "").strip():
        reasons.append("analog_weather_source_required")

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
        "weather_sources": {"observed": request.observed_source, "analog": request.analog_source},
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
    rejected: list[dict[str, Any]] = []
    incomplete: list[int] = []
    for year, series in sorted(request.analog_years.items()):
        if year >= request.as_of.year:
            rejected.append({"year": year, "reasons": ["analog_year_not_before_as_of_season"]})
            continue
        season, problems = validate_analog_season(year, series, request.as_of, request.horizon_days)
        if problems:
            rejected.append({"year": year, "reasons": problems})
            continue
        start = _same_day_in_year(request.as_of, year)
        days_low = _days_to_reach(start, target.low_gdd - accumulated, season, request.config, request.horizon_days)
        days_high = _days_to_reach(start, target.high_gdd - accumulated, season, request.config, request.horizon_days)
        if days_low is None or days_high is None:
            incomplete.append(year)
            continue
        start_offsets.append(days_low)
        end_offsets.append(days_high)
    base["analog_years_rejected"] = rejected
    base["analog_years_unusable"] = incomplete
    if len(start_offsets) < MIN_ANALOG_YEARS:
        return {
            **base, "status": "insufficient_evidence", "window": None,
            "reasons": [f"analog_years_usable:{len(start_offsets)}<{MIN_ANALOG_YEARS}"],
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
    }


HARVEST_SUGGESTION_HORIZON_DAYS = 30
HARVEST_ACTION_CODES = (
    "verify_maturity_by_sampling",
    "confirm_harvest_labor_and_equipment",
    "confirm_storage_transport_and_buyer_commitments",
)


def harvest_action_suggestions(window_result: dict[str, Any], today: date) -> list[dict[str, Any]]:
    """Suggested preparation steps when a supported window is near.

    Suggestions are machine codes for the portal to localize. They never
    create tasks, change contracts, or schedule equipment: each needs a
    person to review and, if appropriate, turn it into a task.
    """
    status = window_result.get("status")
    window = window_result.get("window") or {}
    if status not in {"projected", "within_target_range"} or not window.get("earliest"):
        return []
    earliest = date.fromisoformat(window["earliest"])
    if status == "projected" and (earliest - today).days > HARVEST_SUGGESTION_HORIZON_DAYS:
        return []
    if window.get("latest") and date.fromisoformat(window["latest"]) < today:
        return []  # the window has already ended: nothing left to prepare for
    due = max(today, earliest - timedelta(days=7))
    return [
        {"action_code": code, "due_by": due.isoformat(), "requires_approval": True, "creates_task": False,
         "basis": f"harvest_window_{status}"}
        for code in HARVEST_ACTION_CODES
    ]


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
class Stratum:
    stratum_id: str
    population_units: int                      # N_h: units in this stratum
    sample_counts: Sequence[float]             # visible count per sampled unit in this stratum


@dataclass
class ProductionRequest:
    unit: str                                  # e.g. "vine", "tree", "row_meter"
    object_label: str                          # e.g. "cluster"
    design: str
    population_units: int                      # N: units in the block
    sample_counts: Sequence[float]             # visible count per sampled unit (unstratified designs)
    count_source: str
    detection_rate: Estimate | None = None     # visible / true objects, from paired hand counts
    unit_weight_kg: Estimate | None = None     # mass per object
    marketable_fraction: Estimate | None = None
    area_hectares: Decimal | None = None
    detector_validation_id: str | None = None
    strata: Sequence[Stratum] | None = None    # required for, and only for, stratified_random


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ratio_cv(estimate: Estimate | None) -> float:
    if estimate is None or estimate.value == 0:
        return 0.0
    return estimate.standard_error / estimate.value


STRATIFIED_DESIGN = "stratified_random"
MAX_SAMPLED_UNITS = 5000


def _simple_random_mean(counts: Sequence[float], population_units: int) -> tuple[float, float, int, list[str]]:
    """Mean per unit, its standard error with finite population correction, degrees of freedom, warnings."""
    n = len(counts)
    mean = sum(counts) / n
    # Identical counts are detected directly: their float variance can be 1e-34 rather than 0.
    degenerate = max(counts) == min(counts)
    variance = 0.0 if degenerate else sum((value - mean) ** 2 for value in counts) / (n - 1)
    warnings = ["zero_sample_variance:sample"] if degenerate and n < population_units else []
    return mean, math.sqrt(variance / n * (1 - n / population_units)), n - 1, warnings


def _stratified_mean(strata: Sequence[Stratum]) -> tuple[float, float, int, list[str]]:
    """Stratified expansion estimator (Cochran, Sampling Techniques, ch. 5).

    Total = sum N_h * ybar_h; Var(total) = sum N_h^2 (1 - n_h/N_h) s_h^2 / n_h.
    Degrees of freedom by Satterthwaite over the strata that contribute
    variance, floored to an integer (conservative, with a tolerance for
    floating-point error) and kept between their min(n_h - 1) and
    sum(n_h - 1). A sampled stratum whose counts happen to be identical adds
    no variance although most of it was not observed, so it is reported as a
    warning rather than as certainty.
    """
    population = sum(stratum.population_units for stratum in strata)
    total = variance = denominator = 0.0
    contributing: list[int] = []
    warnings: list[str] = []
    for stratum in strata:
        counts = [float(value) for value in stratum.sample_counts]
        n_h, big_n = len(counts), stratum.population_units
        mean_h = sum(counts) / n_h
        s2_h = 0.0 if max(counts) == min(counts) else sum((value - mean_h) ** 2 for value in counts) / (n_h - 1)
        a_h = big_n * (big_n - n_h) / n_h
        total += big_n * mean_h
        variance += a_h * s2_h
        if a_h * s2_h > 0:
            contributing.append(n_h - 1)
            denominator += (a_h * s2_h) ** 2 / (n_h - 1)
        elif n_h < big_n:
            warnings.append(f"zero_sample_variance:{stratum.stratum_id}"[:200])
    if contributing and denominator > 0:
        df = max(min(contributing), min(sum(contributing), int(variance ** 2 / denominator + 1e-9)))
    else:
        df = sum(len(stratum.sample_counts) - 1 for stratum in strata)
    return total / population, math.sqrt(variance) / population, max(1, df), warnings


def _strata_problems(request: ProductionRequest) -> list[str]:
    problems: list[str] = []
    strata = list(request.strata or [])
    if request.design != STRATIFIED_DESIGN:
        return ["strata_require_stratified_random_design"] if strata else []
    if len(strata) < 2:
        return ["stratified_random_requires_at_least_2_strata_with_population_and_samples"]
    if request.sample_counts:
        problems.append("stratified_random_uses_per_stratum_counts_not_pooled_sample_counts")
    ids = [str(stratum.stratum_id or "").strip() for stratum in strata]
    if any(not stratum_id for stratum_id in ids) or len(set(ids)) != len(ids):
        problems.append("stratum_ids_must_be_present_and_unique")
    for stratum in strata:
        counts = list(stratum.sample_counts or [])
        population = stratum.population_units
        if isinstance(population, bool) or not isinstance(population, int) or population < len(counts):
            problems.append(f"stratum_population_must_be_an_integer_at_least_its_sample:{stratum.stratum_id}"[:200])
        if len(counts) < 2:
            problems.append(f"stratum_needs_at_least_2_sampled_units:{stratum.stratum_id}"[:200])
        if any(not _finite(value) or value < 0 for value in counts):
            problems.append("sample_counts_must_be_finite_and_non_negative")
    if not problems and request.population_units != sum(stratum.population_units for stratum in strata):
        problems.append("population_units_must_equal_the_sum_of_stratum_populations")
    return problems


def estimate_production(request: ProductionRequest) -> dict[str, Any]:
    """Expansion estimator with finite population correction.

    Total visible objects = N x mean visible per unit. For stratified_random
    the mean is the population-weighted stratified mean, never the pooled
    sample mean, and strata with their population sizes are required.
    Dividing by the detection (visibility) rate gives total objects;
    multiplying by unit weight gives production. Relative standard errors of
    independent factors combine in quadrature (delta method); the interval
    uses the Student t value for the design's degrees of freedom.
    """
    reasons: list[str] = []
    stratified = request.design == STRATIFIED_DESIGN
    if stratified:
        counts = [float(value) for stratum in (request.strata or []) for value in (stratum.sample_counts or [])]
    else:
        counts = [float(value) for value in request.sample_counts]
    n = len(counts)
    if request.design not in PROBABILITY_DESIGNS:
        reasons.append("non_probability_sample_cannot_be_extrapolated")
    reasons.extend(_strata_problems(request))
    if n > MAX_SAMPLED_UNITS:
        reasons.append(f"sampled_units:{n}>{MAX_SAMPLED_UNITS}")
    if request.count_source not in COUNT_SOURCES:
        reasons.append("counts_must_be_manual_or_from_a_validated_detector")
    evaluation = None
    if request.count_source == "validated_detector":
        if not request.detector_validation_id:
            reasons.append("validated_detector_requires_validation_reference")
        else:
            # A client-supplied id is not proof: only the server-side registry verifies a detector.
            evaluation = crop_model_registry.verified_evaluation(request.detector_validation_id)
            if evaluation is None:
                reasons.append("detector_evaluation_not_in_server_registry")
    if n < MIN_SAMPLE_UNITS:
        reasons.append(f"sample_units:{n}<{MIN_SAMPLE_UNITS}")
    if request.population_units <= 0 or request.population_units < n:
        reasons.append("population_units_must_be_known_and_at_least_the_sample")
    if any(not math.isfinite(value) or value < 0 for value in counts):
        reasons.append("sample_counts_must_be_finite_and_non_negative")
    if isinstance(request.population_units, bool) or not isinstance(request.population_units, int):
        reasons.append("population_units_must_be_an_integer")
    for name, estimate in (("detection_rate", request.detection_rate), ("unit_weight_kg", request.unit_weight_kg),
                           ("marketable_fraction", request.marketable_fraction)):
        if estimate is None:
            continue
        # NaN fails every comparison, so finiteness is checked explicitly.
        if not (_finite(estimate.value) and _finite(estimate.standard_error)) or estimate.value <= 0 or estimate.standard_error < 0:
            reasons.append(f"{name}_invalid")
    if request.area_hectares is not None and (not request.area_hectares.is_finite() or request.area_hectares <= 0):
        reasons.append("area_hectares_invalid")
    if request.detection_rate is not None and _finite(request.detection_rate.value) and request.detection_rate.value > 1:
        reasons.append("detection_rate_above_one")
    if request.marketable_fraction is not None and _finite(request.marketable_fraction.value) and request.marketable_fraction.value > 1:
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
        "input_provenance": {
            "sample_counts": (
                f"registry_verified_detector:{evaluation.evaluation_id}" if evaluation is not None
                else "user_supplied_unverified"
            ),
            "calibration": "user_supplied_unverified",
            "population_units": "user_supplied_unverified",
        },
    }
    if evaluation is not None:
        result["detector_evaluation"] = {
            "evaluation_id": evaluation.evaluation_id, "model_id": evaluation.model_id,
            "model_version": evaluation.model_version, "crop_id": evaluation.crop_id,
            "report_ref": evaluation.report_ref, "registry_version": crop_model_registry.REGISTRY_VERSION,
        }
    if reasons:
        return {**result, "status": "not_estimable", "reasons": list(dict.fromkeys(reasons))}
    try:
        computed = _production_body(request, result, counts, stratified)
    except ArithmeticError:  # OverflowError, decimal.InvalidOperation: inputs too large to estimate safely
        computed = None
    if computed is None or not _all_finite(computed):
        return {**result, "status": "not_estimable", "reasons": ["inputs_outside_numeric_range"]}
    return computed


def _all_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_all_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(item) for item in value)
    return True


def _production_body(request: ProductionRequest, result: dict[str, Any], counts: list[float], stratified: bool) -> dict[str, Any]:
    result = dict(result)
    if stratified:
        mean, mean_se, df, warnings = _stratified_mean(list(request.strata or []))
        result["variance_method"] = "stratified_expansion_satterthwaite_df"
        result["strata"] = [
            {"stratum_id": stratum.stratum_id, "population_units": stratum.population_units,
             "sampled_units": len(stratum.sample_counts),
             "mean_visible_per_unit": round(sum(stratum.sample_counts) / len(stratum.sample_counts), 4)}
            for stratum in request.strata or []
        ]
    else:
        mean, mean_se, df, warnings = _simple_random_mean(counts, request.population_units)
        result["variance_method"] = (
            "simple_random_fpc_approximation_for_systematic_sample" if request.design == "systematic_random_start"
            else "simple_random_fpc"
        )
    result["degrees_of_freedom"] = df
    # Identical counts in a partly observed sample add no variance; the interval
    # would claim certainty the data cannot support.
    result["interval_reliability"] = "unreliable_zero_sample_variance" if warnings else "design_based"
    if warnings:
        result["interval_warnings"] = warnings
    critical = t_critical_95(df)
    counted = float(sum(counts))
    density = Estimate(mean, mean_se)
    result["visible_density_per_unit"] = {
        "value": round(mean, 4), "standard_error": round(mean_se, 4),
        "interval_95": [round(bound, 4) for bound in density.interval(critical)],
    }
    visible_total = Estimate(request.population_units * mean, request.population_units * mean_se)
    # A population total can never be below the objects actually counted in it.
    visible_low, visible_high = visible_total.interval(critical)
    result["extrapolated_visible_objects"] = {
        "value": round(visible_total.value, 1), "interval_95": [round(max(visible_low, counted), 1), round(visible_high, 1)],
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
    total_low, total_high = total_objects.interval(critical)
    result["estimated_total_objects"] = {
        # Visibility is at most 1, so total objects are at least the objects counted.
        "value": round(total_objects.value, 1), "interval_95": [round(max(total_low, counted), 1), round(total_high, 1)],
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
        if request.marketable_fraction is not None:
            marketable_per_hectare = Decimal(str(round(production.value * request.marketable_fraction.value, 6))) / request.area_hectares
            result["expected_marketable_kg_per_hectare"] = format(marketable_per_hectare.quantize(Decimal("0.01")), "f")
    result["status"] = "estimated"
    result["interval_method"] = "Student t on the design's degrees of freedom; relative errors of calibration factors combined in quadrature"
    return result


def market_yield_proposal(estimate: dict[str, Any], *, estimate_id: str) -> dict[str, Any] | None:
    """Turn an estimate into a *proposal* for the existing Market Intelligence
    yield-estimate intake. It never applies to expected production by itself:
    ``apply_to_production`` is false so the customer's current values stay in
    force until a person with write access reviews and applies it."""
    if estimate.get("status") != "estimated" or not estimate.get("expected_production_kg_per_hectare"):
        return None
    if estimate.get("interval_reliability") not in (None, "design_based"):
        return None  # never propose a yield whose interval overstates precision
    # Expected production drives commercial exposure, so the sellable volume is
    # proposed when the grower supplied a marketable fraction.
    marketable = estimate.get("expected_marketable_kg_per_hectare") and estimate.get("expected_marketable_kg")
    basis = "marketable production" if marketable else "total production"
    low, high = estimate["expected_marketable_kg" if marketable else "expected_production_kg"]["interval_95"]
    return {
        "yield_per_area": estimate["expected_marketable_kg_per_hectare" if marketable else "expected_production_kg_per_hectare"],
        "quantity_unit": "kg",
        "area_unit": "hectare",
        "source": "crop_intelligence",
        "apply_to_production": False,
        "note": (
            f"Crop Intelligence estimate {estimate_id} ({estimate.get('design')}, n={estimate.get('sampled_units')}, "
            f"{estimate.get('count_source')}); yield basis: {basis}; 95% interval for block {basis} {low}–{high} kg. "
            "Inputs are user-supplied and unverified by AGRO-AI. Review before applying."
        )[:1000],
    }


# ---------------------------------------------------------------------------
# Maturity stage proportions (e.g. almond hull split, tomato colour, coffee ripeness)
# ---------------------------------------------------------------------------

@dataclass
class StageSample:
    unit_id: str                    # sampled tree, vine, plant or branch
    counts: dict[str, float]        # maturity stage -> objects observed on this unit


@dataclass
class ReadinessRule:
    ready_stages: tuple[str, ...]   # stages that count toward readiness
    threshold_share: float          # share of objects at ready stages that defines readiness
    source: str                     # who set the threshold (grower, adviser, published guidance)


@dataclass
class StageProportionRequest:
    crop_id: str
    design: str
    samples: Sequence[StageSample]
    count_source: str
    detector_validation_id: str | None = None
    population_units: int | None = None
    readiness: ReadinessRule | None = None


def _ratio_estimate(y: list[float], m: list[float], population_units: int | None,
                    sampled_units: int | None = None) -> tuple[float, float]:
    """Ratio estimator for a proportion when objects are clustered in sample units.

    p = sum(y) / sum(m); Var(p) = (1 - f) / (n * mbar^2) * sum((y_i - p m_i)^2) / (n - 1).
    The sampling fraction f counts every sampled unit, including units with no objects.
    """
    n = len(m)
    total = sum(m)
    p = sum(y) / total
    mbar = total / n
    sampled = n if sampled_units is None else sampled_units
    fpc = 1 - sampled / population_units if population_units and population_units >= sampled else 1.0
    residual = sum((yi - p * mi) ** 2 for yi, mi in zip(y, m)) / (n - 1)
    return p, math.sqrt(max(fpc, 0.0) * residual / (n * mbar * mbar))


def estimate_stage_proportions(request: StageProportionRequest) -> dict[str, Any]:
    """Share of observed objects at each maturity stage, with honest scope.

    With a probability sample of units the shares carry intervals that
    describe the block; otherwise they describe only the sampled units and
    no readiness call is made. Readiness compares the interval with a
    threshold whose source is stated: ready only when the whole interval is
    at or above it, not ready when it is entirely below, uncertain between.
    """
    from app.services.crop_profiles import get_profile

    reasons: list[str] = []
    profile = get_profile(request.crop_id)
    stages = tuple(profile.maturity_stages) if profile else ()
    if profile is None or not stages:
        reasons.append("crop_profile_has_no_maturity_scale")
    if request.count_source not in COUNT_SOURCES:
        reasons.append("counts_must_be_manual_or_from_a_validated_detector")
    evaluation = None
    if request.count_source == "validated_detector":
        evaluation = crop_model_registry.verified_evaluation(request.detector_validation_id)
        if evaluation is None:
            reasons.append("detector_evaluation_not_in_server_registry")
    duplicates = sorted(unit for unit, seen in Counter(str(sample.unit_id) for sample in request.samples).items() if seen > 1)
    if duplicates:
        # Each sampled tree, vine or plant is one cluster; repeated rows would be pseudo-replication.
        reasons.append(f"duplicate_unit_ids:{','.join(duplicates[:5])}"[:200])
    rows: list[dict[str, float]] = []
    for sample in request.samples:
        counts = dict(sample.counts or {})
        unknown = sorted(set(counts) - set(stages))
        if unknown:
            reasons.append(f"stages_not_in_{request.crop_id}_scale:{','.join(unknown)}"[:200])
            break
        if any(not _finite(value) or value < 0 for value in counts.values()):
            reasons.append("stage_counts_must_be_finite_and_non_negative")
            break
        rows.append(counts)
    units = [row for row in rows if sum(row.values()) > 0]
    if len(units) < MIN_SAMPLE_UNITS:
        reasons.append(f"sample_units_with_objects:{len(units)}<{MIN_SAMPLE_UNITS}")
    population = request.population_units
    if population is not None and (isinstance(population, bool) or not isinstance(population, int)
                                   or population < len(request.samples)):
        reasons.append("population_units_must_be_an_integer_at_least_the_sample")
    rule = request.readiness
    if rule is not None:
        if not rule.ready_stages or any(stage not in stages for stage in rule.ready_stages):
            reasons.append("readiness_stages_not_in_scale")
        if len(set(rule.ready_stages)) != len(rule.ready_stages):
            reasons.append("readiness_stages_must_be_unique")  # a repeated stage would be counted twice
        if not _finite(rule.threshold_share) or not 0 < rule.threshold_share <= 1:
            reasons.append("readiness_threshold_must_be_a_share_in_(0,1]")
        if not str(rule.source or "").strip():
            reasons.append("readiness_threshold_source_required")

    result: dict[str, Any] = {
        "estimation_version": ESTIMATION_VERSION,
        "crop_id": request.crop_id,
        "maturity_scale": profile.maturity_scale if profile else None,
        "design": request.design,
        "sampled_units": len(units),
        "objects_observed": sum(sum(row.values()) for row in units),
        "input_provenance": {
            "stage_counts": (f"registry_verified_detector:{evaluation.evaluation_id}" if evaluation is not None
                             else "user_supplied_unverified"),
        },
    }
    if reasons:
        return {**result, "status": "not_estimable", "reasons": reasons}
    try:
        computed = _stage_body(request, result, units, stages, rule)
    except ArithmeticError:  # counts too large to square safely
        computed = None
    if computed is None or not _all_finite(computed):
        return {**result, "status": "not_estimable", "reasons": ["inputs_outside_numeric_range"]}
    return computed


def _stage_body(request: StageProportionRequest, result: dict[str, Any], units: list[dict[str, float]],
                stages: tuple[str, ...], rule: ReadinessRule | None) -> dict[str, Any]:
    result = dict(result)
    # Pooled cluster ratios are only a block estimate for unstratified probability
    # designs; a stratified sample needs stratum population weights, which this
    # contract does not carry, so it describes the sampled units only.
    probability = request.design in PROBABILITY_DESIGNS and request.design != STRATIFIED_DESIGN
    m = [sum(row.values()) for row in units]
    critical = t_critical_95(len(units) - 1)
    sampled = len(request.samples)
    # Every unit in the population sampled (units with no objects included): no sampling variance.
    census = request.population_units is not None and request.population_units == sampled
    fpc = 1 - sampled / request.population_units if request.population_units else 1.0
    # Units differ in size, so the worst case uses fewer effective units.
    n_eff = len(units) * (sum(m) / len(m)) / max(m)

    def interval(y: list[float]) -> tuple[float, float, str | None]:
        """Never narrower than a bound that holds whatever the spread of unit shares.

        The design-based interval (p +/- t * se) is anti-conservative when few
        units happen to agree: near-identical shares give se close to 0 although
        unsampled units may differ a lot. Unit shares lie in [0, 1], so their
        variance is at most p(1 - p); the reported interval is the union of the
        design-based interval and a Wilson score interval under that worst case,
        so more favourable data can never give a less favourable call.
        """
        p, se = _ratio_estimate(y, m, request.population_units, sampled)
        if census:
            return p, p, None
        design_low, design_high = max(0.0, p - critical * se), min(1.0, p + critical * se)
        n_w = n_eff / fpc  # the finite population correction applies to the worst case too
        z2 = critical * critical
        centre = (p + z2 / (2 * n_w)) / (1 + z2 / n_w)
        half = critical * math.sqrt(p * (1 - p) / n_w + z2 / (4 * n_w * n_w)) / (1 + z2 / n_w)
        worst_low, worst_high = max(0.0, centre - half), min(1.0, centre + half)
        binding = worst_low < design_low or worst_high > design_high
        return (min(design_low, worst_low), max(design_high, worst_high),
                "worst_case_between_unit_variance" if binding else "design_based")

    shares: dict[str, dict[str, Any]] = {}
    for stage in stages:
        y = [row.get(stage, 0.0) for row in units]
        p, _ = _ratio_estimate(y, m, request.population_units, sampled)
        entry: dict[str, Any] = {"share": round(p, 4)}
        if probability:
            low, high, basis = interval(y)
            entry["interval_95"] = [round(low, 4), round(high, 4)]
            if basis:
                entry["interval_basis"] = basis
        shares[stage] = entry
    result["stage_shares"] = shares
    result["scope"] = "block_estimate" if probability else "sampled_units_only"
    if request.design == STRATIFIED_DESIGN:
        result["scope_reason"] = "stratified_design_needs_stratum_population_weights"

    if rule is not None:
        y = [sum(row.get(stage, 0.0) for stage in rule.ready_stages) for row in units]
        p, _ = _ratio_estimate(y, m, request.population_units, sampled)
        readiness: dict[str, Any] = {
            "ready_stages": list(rule.ready_stages), "threshold_share": rule.threshold_share,
            "threshold_source": rule.source, "observed_share": round(p, 4),
        }
        if not probability:
            readiness["status"] = (
                "not_assessed_stratified_without_stratum_weights" if request.design == STRATIFIED_DESIGN
                else "not_assessed_non_probability_sample"
            )
        else:
            low, high, basis = interval(y)
            readiness["interval_95"] = [round(low, 4), round(high, 4)]
            if basis:
                readiness["interval_basis"] = basis
            readiness["status"] = "ready" if low >= rule.threshold_share else "not_ready" if high < rule.threshold_share else "uncertain"
        result["readiness"] = readiness
    result["status"] = "estimated"
    result["interval_method"] = (
        "ratio estimator with sample units as clusters (Student t on units), widened where needed to a Wilson "
        "bound under the worst-case between-unit variance p(1 - p)"
    )
    return result

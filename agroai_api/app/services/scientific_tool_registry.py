"""Versioned deterministic scientific tools for AGRO-AI.

Every registered tool is fail closed. It computes only from explicit inputs,
returns exact missing requirements, or rejects invalid inputs. It never fills
an agronomic parameter from model knowledge, a crop label, or a hidden default.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


ToolStatus = Literal["COMPUTED", "NOT_COMPUTABLE", "INVALID_INPUT"]
DEFAULT_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


class ScientificToolSpec(BaseModel):
    tool_id: str
    version: str
    domain: str
    description: str
    required_inputs: list[str]
    optional_inputs: list[str] = Field(default_factory=list)
    expected_units: dict[str, str] = Field(default_factory=dict)
    unit_normalization: dict[str, str] = Field(default_factory=dict)
    valid_ranges: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, str]
    calculation_method: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: list[dict[str, str]] = Field(default_factory=list)


class ScientificToolResult(BaseModel):
    tool_id: str
    version: str
    status: ToolStatus
    output: dict[str, Any] = Field(default_factory=dict)
    normalized_inputs: dict[str, Any] = Field(default_factory=dict)
    missing_requirements: list[str] = Field(default_factory=list)
    invalid_inputs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


ToolRunner = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def _number(inputs: dict[str, Any], name: str, *, positive: bool = False) -> float:
    value = inputs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name)
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0) or (not positive and number < 0):
        raise ValueError(name)
    return number


def _finite_number(inputs: dict[str, Any], name: str) -> float:
    value = inputs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(name)
    return number


def _fraction(inputs: dict[str, Any], name: str) -> float:
    value = _finite_number(inputs, name)
    if value < 0 or value > 1:
        raise ValueError(name)
    return value


def _parse_time(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(name) from exc
    else:
        raise ValueError(name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ScientificToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ScientificToolSpec, ToolRunner]] = {}

    def register(self, spec: ScientificToolSpec, runner: ToolRunner) -> None:
        if spec.tool_id in self._tools:
            raise ValueError(f"Scientific tool already registered: {spec.tool_id}")
        self._tools[spec.tool_id] = (spec, runner)

    def specs(self) -> list[ScientificToolSpec]:
        return [entry[0] for entry in self._tools.values()]

    def spec(self, tool_id: str) -> ScientificToolSpec:
        try:
            return self._tools[tool_id][0]
        except KeyError as exc:
            raise KeyError(f"Unknown scientific tool: {tool_id}") from exc

    def run(self, tool_id: str, inputs: dict[str, Any]) -> ScientificToolResult:
        try:
            spec, runner = self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown scientific tool: {tool_id}") from exc
        missing = [name for name in spec.required_inputs if inputs.get(name) is None]
        if missing:
            return ScientificToolResult(
                tool_id=spec.tool_id,
                version=spec.version,
                status="NOT_COMPUTABLE",
                missing_requirements=missing,
                assumptions=spec.assumptions,
                limitations=spec.limitations,
            )
        try:
            output, normalized = runner(inputs)
        except ValueError as exc:
            return ScientificToolResult(
                tool_id=spec.tool_id,
                version=spec.version,
                status="INVALID_INPUT",
                invalid_inputs=[str(exc) if str(exc) else "invalid_input"],
                assumptions=spec.assumptions,
                limitations=spec.limitations,
            )
        return ScientificToolResult(
            tool_id=spec.tool_id,
            version=spec.version,
            status="COMPUTED",
            output=output,
            normalized_inputs=normalized,
            assumptions=spec.assumptions,
            limitations=spec.limitations,
        )


REGISTRY = ScientificToolRegistry()


def _register(
    *, tool_id: str, domain: str, description: str, required_inputs: list[str],
    expected_units: dict[str, str], valid_ranges: dict[str, str], output_schema: dict[str, str],
    calculation_method: str, runner: ToolRunner, assumptions: list[str] | None = None,
    limitations: list[str] | None = None, provenance: list[dict[str, str]] | None = None,
    optional_inputs: list[str] | None = None, unit_normalization: dict[str, str] | None = None,
) -> None:
    REGISTRY.register(
        ScientificToolSpec(
            tool_id=tool_id,
            version="1.0.0",
            domain=domain,
            description=description,
            required_inputs=required_inputs,
            optional_inputs=optional_inputs or [],
            expected_units=expected_units,
            unit_normalization=unit_normalization or {
                name: f"Caller supplies {unit}; use units.convert.v1 before this tool when needed."
                for name, unit in expected_units.items()
            },
            valid_ranges=valid_ranges,
            output_schema=output_schema,
            calculation_method=calculation_method,
            assumptions=assumptions or [],
            limitations=limitations or [],
            provenance=provenance or [],
        ),
        runner,
    )


def _etc(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    eto = _number(inputs, "eto_mm")
    kc = _number(inputs, "kc", positive=True)
    return {"etc_mm": eto * kc}, {"eto_mm": eto, "kc": kc}


def _measured_volume(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    flow = _number(inputs, "flow_m3h")
    runtime = _number(inputs, "runtime_minutes")
    return {"volume_m3": flow * runtime / 60.0}, {"flow_m3h": flow, "runtime_minutes": runtime}


def _depth_from_volume(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    volume = _number(inputs, "volume_m3")
    area = _number(inputs, "area_ha", positive=True)
    return {"depth_mm": volume / (area * 10.0)}, {"volume_m3": volume, "area_ha": area}


def _volume_from_depth(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    depth = _number(inputs, "depth_mm")
    area = _number(inputs, "area_ha", positive=True)
    return {"volume_m3": depth * area * 10.0}, {"depth_mm": depth, "area_ha": area}


def _gross_requirement(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    net = _number(inputs, "net_requirement_mm")
    efficiency = _number(inputs, "efficiency", positive=True)
    if efficiency > 1:
        raise ValueError("efficiency")
    return {"gross_requirement_mm": net / efficiency}, {"net_requirement_mm": net, "efficiency": efficiency}


def _duration(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    volume = _number(inputs, "required_volume_m3")
    flow = _number(inputs, "validated_flow_m3h", positive=True)
    return {"duration_minutes": volume / flow * 60.0}, {"required_volume_m3": volume, "validated_flow_m3h": flow}


def _total_available_water(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fc = _fraction(inputs, "field_capacity_vwc_fraction")
    wp = _fraction(inputs, "wilting_point_vwc_fraction")
    depth = _number(inputs, "root_zone_depth_m", positive=True)
    if fc <= wp:
        raise ValueError("field_capacity_must_exceed_wilting_point")
    taw = (fc - wp) * depth * 1000.0
    return {"total_available_water_mm": taw}, {
        "field_capacity_vwc_fraction": fc,
        "wilting_point_vwc_fraction": wp,
        "root_zone_depth_m": depth,
    }


def _root_zone_storage(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    vwc = _fraction(inputs, "vwc_fraction")
    depth = _number(inputs, "root_zone_depth_m", positive=True)
    return {"root_zone_water_storage_mm": vwc * depth * 1000.0}, {"vwc_fraction": vwc, "root_zone_depth_m": depth}


def _root_zone_depletion(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fc = _fraction(inputs, "field_capacity_vwc_fraction")
    current = _fraction(inputs, "current_vwc_fraction")
    depth = _number(inputs, "root_zone_depth_m", positive=True)
    depletion = (fc - current) * depth * 1000.0
    return {
        "depletion_from_field_capacity_mm": depletion,
        "above_field_capacity": current > fc,
    }, {
        "field_capacity_vwc_fraction": fc,
        "current_vwc_fraction": current,
        "root_zone_depth_m": depth,
    }


def _readily_available_water(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    taw = _number(inputs, "total_available_water_mm")
    mad = _fraction(inputs, "management_allowable_depletion_fraction")
    return {"readily_available_water_mm": taw * mad}, {
        "total_available_water_mm": taw,
        "management_allowable_depletion_fraction": mad,
    }


def _water_balance(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    names = (
        "opening_storage_mm", "effective_rainfall_mm", "irrigation_mm", "capillary_rise_mm",
        "crop_et_mm", "runoff_mm", "deep_percolation_mm",
    )
    values = {name: _number(inputs, name) for name in names}
    inflow = values["effective_rainfall_mm"] + values["irrigation_mm"] + values["capillary_rise_mm"]
    outflow = values["crop_et_mm"] + values["runoff_mm"] + values["deep_percolation_mm"]
    change = inflow - outflow
    closing = values["opening_storage_mm"] + change
    return {
        "inflow_mm": inflow,
        "outflow_mm": outflow,
        "storage_change_mm": change,
        "closing_storage_mm": closing,
    }, values


def _distribution_uniformity_lq(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = inputs.get("application_depths_mm")
    if not isinstance(raw, list) or len(raw) < 4:
        raise ValueError("application_depths_mm")
    values: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError("application_depths_mm")
        values.append(float(value))
    count_raw = inputs.get("lower_quarter_count")
    if isinstance(count_raw, bool) or not isinstance(count_raw, int) or count_raw <= 0:
        raise ValueError("lower_quarter_count")
    if count_raw * 4 != len(values):
        raise ValueError("lower_quarter_count_must_equal_exact_quarter_of_samples")
    overall = sum(values) / len(values)
    if overall <= 0:
        raise ValueError("mean_application_depth_must_be_positive")
    low_average = sum(sorted(values)[:count_raw]) / count_raw
    du = low_average / overall
    return {
        "lower_quarter_average_mm": low_average,
        "overall_average_mm": overall,
        "distribution_uniformity_fraction": du,
        "distribution_uniformity_percent": du * 100.0,
    }, {"application_depths_mm": values, "lower_quarter_count": count_raw}


def _gdd_simple(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tmax = _finite_number(inputs, "tmax_c")
    tmin = _finite_number(inputs, "tmin_c")
    base = _finite_number(inputs, "base_temperature_c")
    if tmax < tmin:
        raise ValueError("tmax_must_be_greater_than_or_equal_to_tmin")
    mean = (tmax + tmin) / 2.0
    raw = mean - base
    return {"mean_temperature_c": mean, "raw_degree_days_c": raw, "gdd_c_days": max(0.0, raw)}, {
        "tmax_c": tmax, "tmin_c": tmin, "base_temperature_c": base,
    }


def _nutrient_mass_from_solution(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    concentration = _number(inputs, "concentration_mg_l")
    volume = _number(inputs, "solution_volume_m3")
    # 1 mg/L = 1 g/m3; divide grams by 1000 for kg.
    mass_kg = concentration * volume / 1000.0
    return {"solute_mass_kg": mass_kg}, {"concentration_mg_l": concentration, "solution_volume_m3": volume}


def _nutrient_mass_from_product(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    product = _number(inputs, "product_mass_kg")
    fraction = _fraction(inputs, "nutrient_mass_fraction")
    return {"nutrient_mass_kg": product * fraction}, {"product_mass_kg": product, "nutrient_mass_fraction": fraction}


def _agreement(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    left = _finite_number(inputs, "value_a")
    right = _finite_number(inputs, "value_b")
    tolerance = _number(inputs, "tolerance")
    mode = str(inputs.get("mode") or "").strip().casefold()
    absolute = abs(left - right)
    if mode == "absolute":
        difference = absolute
    elif mode == "relative":
        denominator = max(abs(left), abs(right))
        difference = 0.0 if denominator == 0 else absolute / denominator
    else:
        raise ValueError("mode")
    return {"difference": difference, "within_tolerance": difference <= tolerance, "mode": mode}, {
        "value_a": left, "value_b": right, "tolerance": tolerance, "mode": mode,
    }


_UNIT_FACTORS_TO_BASE = {
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "in": ("length", 0.0254),
    "m3": ("volume", 1.0), "l": ("volume", 0.001), "gal_us": ("volume", 0.003785411784),
    "ha": ("area", 10_000.0), "m2": ("area", 1.0), "acre": ("area", 4046.8564224),
    "g": ("mass", 0.001), "kg": ("mass", 1.0), "lb": ("mass", 0.45359237),
    "min": ("time", 60.0), "h": ("time", 3600.0), "day": ("time", 86400.0),
}


def _convert(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _finite_number(inputs, "value")
    source = str(inputs.get("from_unit") or "").strip().lower()
    target = str(inputs.get("to_unit") or "").strip().lower()
    if source not in _UNIT_FACTORS_TO_BASE:
        raise ValueError("from_unit")
    if target not in _UNIT_FACTORS_TO_BASE:
        raise ValueError("to_unit")
    source_dimension, source_factor = _UNIT_FACTORS_TO_BASE[source]
    target_dimension, target_factor = _UNIT_FACTORS_TO_BASE[target]
    if source_dimension != target_dimension:
        raise ValueError("unit_dimension")
    return {"value": value * source_factor / target_factor, "unit": target}, {"value": value, "from_unit": source, "to_unit": target}


def _freshness(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = _parse_time(inputs.get("observed_at"), "observed_at")
    evaluated = _parse_time(inputs.get("evaluated_at"), "evaluated_at")
    max_age = _number(inputs, "max_age_hours")
    if observed > evaluated + DEFAULT_CLOCK_SKEW_TOLERANCE:
        raise ValueError("observed_at_future")
    age = max(0.0, (evaluated - observed).total_seconds() / 3600.0)
    return {"age_hours": age, "fresh": age <= max_age}, {
        "observed_at": observed.isoformat(), "evaluated_at": evaluated.isoformat(), "max_age_hours": max_age,
    }


def _plausibility(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _finite_number(inputs, "value")
    minimum = _finite_number(inputs, "min_value")
    maximum = _finite_number(inputs, "max_value")
    if minimum > maximum:
        raise ValueError("range")
    return {"plausible": minimum <= value <= maximum}, {
        "value": value, "min_value": minimum, "max_value": maximum, "unit": str(inputs.get("unit") or ""),
    }


_FAO56 = [{"authority": "FAO", "reference": "Crop evapotranspiration, FAO Irrigation and Drainage Paper 56"}]

_register(
    tool_id="fao56.etc.single_kc.v1", domain="crop_water",
    description="Compute crop evapotranspiration from explicit reference ETo and crop coefficient Kc.",
    required_inputs=["eto_mm", "kc"], expected_units={"eto_mm": "mm per matching time period", "kc": "dimensionless"},
    valid_ranges={"eto_mm": ">= 0", "kc": "> 0; source must justify crop and stage scope"}, output_schema={"etc_mm": "number"},
    calculation_method="ETc = Kc × ETo", runner=_etc,
    assumptions=["ETo and Kc have compatible field, crop-stage, and time scope."],
    limitations=["This is not a complete irrigation requirement or schedule."], provenance=_FAO56,
)
_register(
    tool_id="soil.total_available_water.v1", domain="soil_water",
    description="Compute total available water in an explicit root zone from field capacity and wilting point volumetric water content.",
    required_inputs=["field_capacity_vwc_fraction", "wilting_point_vwc_fraction", "root_zone_depth_m"],
    expected_units={"field_capacity_vwc_fraction": "m3/m3 fraction", "wilting_point_vwc_fraction": "m3/m3 fraction", "root_zone_depth_m": "m"},
    valid_ranges={"field_capacity_vwc_fraction": "0..1 and > wilting point", "wilting_point_vwc_fraction": "0..1", "root_zone_depth_m": "> 0"},
    output_schema={"total_available_water_mm": "number"}, calculation_method="TAW = 1000 × (theta_FC − theta_WP) × root-zone depth(m)",
    runner=_total_available_water, limitations=["Field capacity, wilting point, and effective root-zone depth must be field-appropriate explicit inputs."], provenance=_FAO56,
)
_register(
    tool_id="soil.root_zone_storage.v1", domain="soil_water",
    description="Compute total water storage represented by an explicit uniform volumetric water content over an explicit root-zone depth.",
    required_inputs=["vwc_fraction", "root_zone_depth_m"], expected_units={"vwc_fraction": "m3/m3 fraction", "root_zone_depth_m": "m"},
    valid_ranges={"vwc_fraction": "0..1", "root_zone_depth_m": "> 0"}, output_schema={"root_zone_water_storage_mm": "number"},
    calculation_method="Storage(mm) = VWC × root-zone depth(m) × 1000", runner=_root_zone_storage,
    assumptions=["The supplied VWC represents the stated root-zone depth."],
    limitations=["This is total stored water, not automatically plant-available water."],
)
_register(
    tool_id="soil.depletion_from_field_capacity.v1", domain="soil_water",
    description="Compute signed root-zone depletion from explicit field-capacity and current VWC values.",
    required_inputs=["field_capacity_vwc_fraction", "current_vwc_fraction", "root_zone_depth_m"],
    expected_units={"field_capacity_vwc_fraction": "m3/m3 fraction", "current_vwc_fraction": "m3/m3 fraction", "root_zone_depth_m": "m"},
    valid_ranges={"field_capacity_vwc_fraction": "0..1", "current_vwc_fraction": "0..1", "root_zone_depth_m": "> 0"},
    output_schema={"depletion_from_field_capacity_mm": "number", "above_field_capacity": "boolean"},
    calculation_method="Depletion(mm) = (theta_FC − theta_current) × root-zone depth(m) × 1000", runner=_root_zone_depletion,
    limitations=["Negative depletion is preserved and means the supplied current VWC exceeds the supplied field capacity; the tool does not clamp it."],
)
_register(
    tool_id="soil.readily_available_water.v1", domain="soil_water",
    description="Compute readily available water from explicit total available water and an explicit management allowable depletion fraction.",
    required_inputs=["total_available_water_mm", "management_allowable_depletion_fraction"],
    expected_units={"total_available_water_mm": "mm", "management_allowable_depletion_fraction": "dimensionless fraction"},
    valid_ranges={"total_available_water_mm": ">= 0", "management_allowable_depletion_fraction": "0..1"},
    output_schema={"readily_available_water_mm": "number"}, calculation_method="RAW = TAW × allowable depletion fraction", runner=_readily_available_water,
    limitations=["The allowable depletion fraction must be supplied from an approved crop/stage/management source; this tool never selects it."], provenance=_FAO56,
)
_register(
    tool_id="water.balance.identity.v1", domain="water_balance",
    description="Compute a conservation-accounting water balance from explicit storage, inflow, and outflow terms.",
    required_inputs=["opening_storage_mm", "effective_rainfall_mm", "irrigation_mm", "capillary_rise_mm", "crop_et_mm", "runoff_mm", "deep_percolation_mm"],
    expected_units={name: "mm over the same area and accounting period" for name in ["opening_storage_mm", "effective_rainfall_mm", "irrigation_mm", "capillary_rise_mm", "crop_et_mm", "runoff_mm", "deep_percolation_mm"]},
    valid_ranges={name: ">= 0" for name in ["opening_storage_mm", "effective_rainfall_mm", "irrigation_mm", "capillary_rise_mm", "crop_et_mm", "runoff_mm", "deep_percolation_mm"]},
    output_schema={"inflow_mm": "number", "outflow_mm": "number", "storage_change_mm": "number", "closing_storage_mm": "number"},
    calculation_method="Closing storage = opening storage + effective rainfall + irrigation + capillary rise − crop ET − runoff − deep percolation",
    runner=_water_balance,
    limitations=["Every term must refer to the same spatial area and time period.", "A negative computed closing storage is retained as an accounting inconsistency/deficit signal; it is not silently clamped."],
)
_register(
    tool_id="irrigation.measured_volume.v1", domain="irrigation_measurement",
    description="Compute measured volume from explicit flow and runtime.", required_inputs=["flow_m3h", "runtime_minutes"],
    expected_units={"flow_m3h": "m3/h", "runtime_minutes": "min"}, valid_ranges={"flow_m3h": ">= 0", "runtime_minutes": ">= 0"},
    output_schema={"volume_m3": "number"}, calculation_method="Volume = flow × runtime", runner=_measured_volume,
    limitations=["Flow must represent the same interval and system segment as runtime."],
)
_register(
    tool_id="irrigation.applied_depth.v1", domain="irrigation_measurement",
    description="Compute gross applied depth from measured volume and irrigated area.", required_inputs=["volume_m3", "area_ha"],
    expected_units={"volume_m3": "m3", "area_ha": "ha"}, valid_ranges={"volume_m3": ">= 0", "area_ha": "> 0"},
    output_schema={"depth_mm": "number"}, calculation_method="Depth(mm) = volume(m3) ÷ (area(ha) × 10)", runner=_depth_from_volume,
    limitations=["No application-efficiency or distribution-uniformity correction is inferred."],
)
_register(
    tool_id="irrigation.volume_from_depth.v1", domain="irrigation_planning",
    description="Compute required volume from an already justified depth and explicit area.", required_inputs=["depth_mm", "area_ha"],
    expected_units={"depth_mm": "mm", "area_ha": "ha"}, valid_ranges={"depth_mm": ">= 0", "area_ha": "> 0"},
    output_schema={"volume_m3": "number"}, calculation_method="Volume(m3) = depth(mm) × area(ha) × 10", runner=_volume_from_depth,
)
_register(
    tool_id="irrigation.gross_requirement.v1", domain="irrigation_planning",
    description="Compute gross irrigation requirement from explicit net requirement and efficiency.", required_inputs=["net_requirement_mm", "efficiency"],
    expected_units={"net_requirement_mm": "mm", "efficiency": "dimensionless fraction"}, valid_ranges={"net_requirement_mm": ">= 0", "efficiency": "> 0 and <= 1"},
    output_schema={"gross_requirement_mm": "number"}, calculation_method="Gross requirement = net requirement ÷ efficiency", runner=_gross_requirement,
    limitations=["Efficiency must be measured, supplied, or explicitly calibrated outside this tool."],
)
_register(
    tool_id="irrigation.duration_from_validated_flow.v1", domain="irrigation_planning",
    description="Compute runtime from required volume and validated system flow.", required_inputs=["required_volume_m3", "validated_flow_m3h"],
    expected_units={"required_volume_m3": "m3", "validated_flow_m3h": "m3/h"}, valid_ranges={"required_volume_m3": ">= 0", "validated_flow_m3h": "> 0"},
    output_schema={"duration_minutes": "number"}, calculation_method="Duration = required volume ÷ validated flow", runner=_duration,
    limitations=["The caller must validate flow scope, calibration, freshness, and operating conditions."],
)
_register(
    tool_id="irrigation.distribution_uniformity_lq.v1", domain="irrigation_measurement",
    description="Compute lower-quarter distribution uniformity from explicit catch-can/application-depth measurements.",
    required_inputs=["application_depths_mm", "lower_quarter_count"], expected_units={"application_depths_mm": "list of mm", "lower_quarter_count": "count"},
    valid_ranges={"application_depths_mm": "at least four finite non-negative samples", "lower_quarter_count": "positive integer exactly one quarter of sample count"},
    output_schema={"lower_quarter_average_mm": "number", "overall_average_mm": "number", "distribution_uniformity_fraction": "number", "distribution_uniformity_percent": "number"},
    calculation_method="DU_lq = average depth in the lowest quarter ÷ average depth over all samples", runner=_distribution_uniformity_lq,
    limitations=["Sampling layout and collection procedure must be appropriate for the irrigation system; this tool only performs the arithmetic."],
)
_register(
    tool_id="phenology.gdd.simple_average.v1", domain="phenology",
    description="Compute daily growing degree days with the simple-average method and an explicit base temperature.",
    required_inputs=["tmax_c", "tmin_c", "base_temperature_c"], expected_units={"tmax_c": "degC", "tmin_c": "degC", "base_temperature_c": "degC"},
    valid_ranges={"tmax_c": "finite and >= Tmin", "tmin_c": "finite and <= Tmax", "base_temperature_c": "finite explicit crop/model parameter"},
    output_schema={"mean_temperature_c": "number", "raw_degree_days_c": "number", "gdd_c_days": "number"},
    calculation_method="GDD = max(0, ((Tmax + Tmin)/2) − Tbase)", runner=_gdd_simple,
    limitations=["No upper-temperature cap, lower-temperature substitution, sine method, or crop-specific base temperature is inferred. Use only when the simple-average convention matches the chosen phenology model."],
)
_register(
    tool_id="nutrients.mass_from_solution.v1", domain="nutrient_accounting",
    description="Compute solute mass from explicit solution concentration and solution volume.", required_inputs=["concentration_mg_l", "solution_volume_m3"],
    expected_units={"concentration_mg_l": "mg/L", "solution_volume_m3": "m3"}, valid_ranges={"concentration_mg_l": ">= 0", "solution_volume_m3": ">= 0"},
    output_schema={"solute_mass_kg": "number"}, calculation_method="Solute mass(kg) = concentration(mg/L) × volume(m3) ÷ 1000", runner=_nutrient_mass_from_solution,
    limitations=["This is mass accounting only. It does not determine crop requirement, safe application rate, formulation compatibility, or regulatory compliance."],
)
_register(
    tool_id="nutrients.mass_from_product_fraction.v1", domain="nutrient_accounting",
    description="Compute nutrient mass from explicit product mass and nutrient mass fraction.", required_inputs=["product_mass_kg", "nutrient_mass_fraction"],
    expected_units={"product_mass_kg": "kg", "nutrient_mass_fraction": "dimensionless fraction"}, valid_ranges={"product_mass_kg": ">= 0", "nutrient_mass_fraction": "0..1"},
    output_schema={"nutrient_mass_kg": "number"}, calculation_method="Nutrient mass = product mass × nutrient mass fraction", runner=_nutrient_mass_from_product,
    limitations=["The product analysis/fraction must come from an authoritative label or supplied specification. This tool does not recommend a dose."],
)
_register(
    tool_id="evidence.numeric_agreement.v1", domain="evidence_quality",
    description="Compare two explicit numeric measurements against a caller-supplied absolute or relative tolerance.",
    required_inputs=["value_a", "value_b", "tolerance", "mode"], expected_units={"value_a": "same native unit", "value_b": "same native unit", "tolerance": "native unit for absolute mode or fraction for relative mode"},
    valid_ranges={"value_a": "finite", "value_b": "finite", "tolerance": ">= 0", "mode": "absolute or relative"},
    output_schema={"difference": "number", "within_tolerance": "boolean", "mode": "string"}, calculation_method="Absolute: |a-b|. Relative: |a-b| / max(|a|,|b|), with 0/0 defined as 0.", runner=_agreement,
    limitations=["The tolerance must come from sensor calibration, domain policy, or another explicit approved source; this tool never selects it."],
)
_register(
    tool_id="units.convert.v1", domain="units", description="Convert between supported units with dimensional validation.",
    required_inputs=["value", "from_unit", "to_unit"], expected_units={}, unit_normalization={"value": "Exact factor conversion through the registered SI base dimension."},
    valid_ranges={"value": "finite", "from_unit": "registered unit", "to_unit": "same registered dimension"}, output_schema={"value": "number", "unit": "string"},
    calculation_method="Exact or standardized dimensional conversion through an SI base unit.", runner=_convert,
)
_register(
    tool_id="evidence.freshness.v1", domain="evidence_quality", description="Evaluate source age against an explicit caller-supplied freshness requirement.",
    required_inputs=["observed_at", "evaluated_at", "max_age_hours"], expected_units={"max_age_hours": "h"},
    valid_ranges={"observed_at": "valid timestamp not materially in the future", "evaluated_at": "valid timestamp", "max_age_hours": ">= 0"},
    output_schema={"age_hours": "number", "fresh": "boolean"}, calculation_method="Age = evaluation time − observation time; reject material future timestamps; compare to supplied maximum age.", runner=_freshness,
    limitations=["This tool does not invent a domain-specific freshness threshold.", "A five-minute clock-skew tolerance is an ingestion-safety allowance, not evidence freshness permission."],
)
_register(
    tool_id="sensor.plausibility.v1", domain="evidence_quality", description="Check a sensor value against explicit source- or calibration-specific bounds.",
    required_inputs=["value", "min_value", "max_value"], optional_inputs=["unit"], expected_units={},
    unit_normalization={"value": "Value and supplied bounds must use the same caller-declared unit."},
    valid_ranges={"value": "finite", "min_value": "finite and <= max_value", "max_value": "finite and >= min_value"},
    output_schema={"plausible": "boolean"}, calculation_method="minimum <= value <= maximum", runner=_plausibility,
    limitations=["Bounds must come from sensor documentation, calibration, or an approved policy."],
)


def get_scientific_tool_registry() -> ScientificToolRegistry:
    return REGISTRY

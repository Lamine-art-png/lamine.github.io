"""Versioned deterministic scientific tools for AGRO-AI.

The registry is intentionally small and fail closed.  A tool either computes
from explicit inputs, reports the exact missing requirements, or rejects the
input.  It never fills an agronomic parameter from model knowledge or a hidden
default.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


ToolStatus = Literal["COMPUTED", "NOT_COMPUTABLE", "INVALID_INPUT"]


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
            invalid = [str(exc)] if str(exc) else ["invalid_input"]
            return ScientificToolResult(
                tool_id=spec.tool_id,
                version=spec.version,
                status="INVALID_INPUT",
                invalid_inputs=invalid,
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
    *,
    tool_id: str,
    domain: str,
    description: str,
    required_inputs: list[str],
    expected_units: dict[str, str],
    valid_ranges: dict[str, str],
    output_schema: dict[str, str],
    calculation_method: str,
    runner: ToolRunner,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
    provenance: list[dict[str, str]] | None = None,
    optional_inputs: list[str] | None = None,
    unit_normalization: dict[str, str] | None = None,
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


_UNIT_FACTORS_TO_BASE = {
    "mm": ("length", 0.001),
    "m": ("length", 1.0),
    "in": ("length", 0.0254),
    "m3": ("volume", 1.0),
    "l": ("volume", 0.001),
    "gal_us": ("volume", 0.003785411784),
    "ha": ("area", 10_000.0),
    "m2": ("area", 1.0),
    "acre": ("area", 4046.8564224),
    "min": ("time", 60.0),
    "h": ("time", 3600.0),
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
    return {"value": value * source_factor / target_factor, "unit": target}, {
        "value": value,
        "from_unit": source,
        "to_unit": target,
    }


def _freshness(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = _parse_time(inputs.get("observed_at"), "observed_at")
    evaluated = _parse_time(inputs.get("evaluated_at"), "evaluated_at")
    max_age = _number(inputs, "max_age_hours")
    age = max(0.0, (evaluated - observed).total_seconds() / 3600.0)
    return {"age_hours": age, "fresh": age <= max_age}, {
        "observed_at": observed.isoformat(),
        "evaluated_at": evaluated.isoformat(),
        "max_age_hours": max_age,
    }


def _plausibility(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _finite_number(inputs, "value")
    minimum = _finite_number(inputs, "min_value")
    maximum = _finite_number(inputs, "max_value")
    if minimum > maximum:
        raise ValueError("range")
    return {"plausible": minimum <= value <= maximum}, {
        "value": value,
        "min_value": minimum,
        "max_value": maximum,
        "unit": str(inputs.get("unit") or ""),
    }


_register(
    tool_id="fao56.etc.single_kc.v1",
    domain="crop_water",
    description="Compute crop evapotranspiration from explicit reference ETo and crop coefficient Kc.",
    required_inputs=["eto_mm", "kc"],
    expected_units={"eto_mm": "mm per matching time period", "kc": "dimensionless"},
    valid_ranges={"eto_mm": ">= 0", "kc": "> 0; source must justify crop and stage scope"},
    output_schema={"etc_mm": "number"},
    calculation_method="ETc = Kc × ETo",
    runner=_etc,
    assumptions=["ETo and Kc have compatible field, crop-stage, and time scope."],
    limitations=["This is not a complete irrigation requirement or schedule."],
    provenance=[{"authority": "FAO", "reference": "Crop evapotranspiration (FAO Irrigation and Drainage Paper 56)"}],
)
_register(
    tool_id="irrigation.measured_volume.v1",
    domain="irrigation_measurement",
    description="Compute measured volume from explicit flow and runtime.",
    required_inputs=["flow_m3h", "runtime_minutes"],
    expected_units={"flow_m3h": "m3/h", "runtime_minutes": "min"},
    valid_ranges={"flow_m3h": ">= 0", "runtime_minutes": ">= 0"},
    output_schema={"volume_m3": "number"},
    calculation_method="Volume = flow × runtime",
    runner=_measured_volume,
    limitations=["Flow must represent the same interval and system segment as runtime."],
)
_register(
    tool_id="irrigation.applied_depth.v1",
    domain="irrigation_measurement",
    description="Compute gross applied depth from measured volume and irrigated area.",
    required_inputs=["volume_m3", "area_ha"],
    expected_units={"volume_m3": "m3", "area_ha": "ha"},
    valid_ranges={"volume_m3": ">= 0", "area_ha": "> 0"},
    output_schema={"depth_mm": "number"},
    calculation_method="Depth(mm) = volume(m3) ÷ (area(ha) × 10)",
    runner=_depth_from_volume,
    limitations=["No application-efficiency or distribution-uniformity correction is inferred."],
)
_register(
    tool_id="irrigation.volume_from_depth.v1",
    domain="irrigation_planning",
    description="Compute required volume from an already justified depth and explicit area.",
    required_inputs=["depth_mm", "area_ha"],
    expected_units={"depth_mm": "mm", "area_ha": "ha"},
    valid_ranges={"depth_mm": ">= 0", "area_ha": "> 0"},
    output_schema={"volume_m3": "number"},
    calculation_method="Volume(m3) = depth(mm) × area(ha) × 10",
    runner=_volume_from_depth,
)
_register(
    tool_id="irrigation.gross_requirement.v1",
    domain="irrigation_planning",
    description="Compute gross irrigation requirement from explicit net requirement and efficiency.",
    required_inputs=["net_requirement_mm", "efficiency"],
    expected_units={"net_requirement_mm": "mm", "efficiency": "dimensionless fraction"},
    valid_ranges={"net_requirement_mm": ">= 0", "efficiency": "> 0 and <= 1"},
    output_schema={"gross_requirement_mm": "number"},
    calculation_method="Gross requirement = net requirement ÷ efficiency",
    runner=_gross_requirement,
    limitations=["Efficiency must be measured, supplied, or explicitly calibrated outside this tool."],
)
_register(
    tool_id="irrigation.duration_from_validated_flow.v1",
    domain="irrigation_planning",
    description="Compute runtime from required volume and validated system flow.",
    required_inputs=["required_volume_m3", "validated_flow_m3h"],
    expected_units={"required_volume_m3": "m3", "validated_flow_m3h": "m3/h"},
    valid_ranges={"required_volume_m3": ">= 0", "validated_flow_m3h": "> 0"},
    output_schema={"duration_minutes": "number"},
    calculation_method="Duration = required volume ÷ validated flow",
    runner=_duration,
    limitations=["The caller must validate flow scope, calibration, freshness, and operating conditions."],
)
_register(
    tool_id="units.convert.v1",
    domain="units",
    description="Convert between supported units with dimensional validation.",
    required_inputs=["value", "from_unit", "to_unit"],
    expected_units={},
    unit_normalization={"value": "Exact factor conversion through the registered SI base dimension."},
    valid_ranges={"value": "finite", "from_unit": "registered unit", "to_unit": "same registered dimension"},
    output_schema={"value": "number", "unit": "string"},
    calculation_method="Exact or standardized dimensional conversion through an SI base unit.",
    runner=_convert,
)
_register(
    tool_id="evidence.freshness.v1",
    domain="evidence_quality",
    description="Evaluate source age against an explicit caller-supplied freshness requirement.",
    required_inputs=["observed_at", "evaluated_at", "max_age_hours"],
    expected_units={"max_age_hours": "h"},
    valid_ranges={"observed_at": "valid timestamp", "evaluated_at": "valid timestamp", "max_age_hours": ">= 0"},
    output_schema={"age_hours": "number", "fresh": "boolean"},
    calculation_method="Age = evaluation time − observation time; compare to supplied maximum age.",
    runner=_freshness,
    limitations=["This tool does not invent a domain-specific freshness threshold."],
)
_register(
    tool_id="sensor.plausibility.v1",
    domain="evidence_quality",
    description="Check a sensor value against explicit source- or calibration-specific bounds.",
    required_inputs=["value", "min_value", "max_value"],
    optional_inputs=["unit"],
    expected_units={},
    unit_normalization={"value": "Value and supplied bounds must use the same caller-declared unit."},
    valid_ranges={"value": "finite", "min_value": "finite and <= max_value", "max_value": "finite and >= min_value"},
    output_schema={"plausible": "boolean"},
    calculation_method="minimum ≤ value ≤ maximum",
    runner=_plausibility,
    limitations=["Bounds must come from sensor documentation, calibration, or an approved policy."],
)


def get_scientific_tool_registry() -> ScientificToolRegistry:
    return REGISTRY

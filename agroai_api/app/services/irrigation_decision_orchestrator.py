from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.agronomic_decision_kernel import AgronomicDecisionInput, AgronomicDecisionKernelV02
from app.services.intelligence_engine import IntelligenceEngineV1
from app.services.scientific_tool_registry import get_scientific_tool_registry


def _num(value: Any) -> Optional[float]:
    try:
        if value in ("", None, "not available", "provider context pending"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        n = _num(value)
        if n is not None:
            return n
    return None


def _merge_context(base: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overrides:
        return dict(base)
    merged = dict(base)
    for key, value in overrides.items():
        if value not in (None, "", {}, []):
            merged[key] = value
    if "crop_type" in merged:
        merged["crop"] = merged["crop_type"]
    if "soil_type" in merged:
        merged["soil"] = merged["soil_type"]
    if isinstance(merged.get("sensor_context"), dict):
        merged.setdefault("metrics", {})
        sensor = merged["sensor_context"]
        if sensor.get("flow_m3h") is not None:
            merged["metrics"]["flow_m3h"] = sensor.get("flow_m3h")
            merged["flow_evidence"] = {
                "value_m3h": sensor.get("flow_m3h"),
                "provenance": sensor.get("flow_provenance") or sensor.get("provenance"),
                "block": sensor.get("block") or merged.get("block") or merged.get("field_id"),
                "timestamp": sensor.get("timestamp"),
                "pressure_state": sensor.get("pressure_state"),
                "valid_until": sensor.get("valid_until"),
                "max_age_hours": sensor.get("max_age_hours"),
                "calibration_status": sensor.get("calibration_status"),
            }
        if sensor.get("moisture_percent") is not None:
            merged["metrics"]["avg_moisture_percent"] = sensor.get("moisture_percent")
    if isinstance(merged.get("weather_context"), dict):
        merged.setdefault("metrics", {})
        weather = merged["weather_context"]
        if weather.get("eto_mm") is not None:
            merged["metrics"]["avg_eto_mm"] = weather.get("eto_mm")
        if weather.get("precipitation_forecast_mm") is not None:
            merged["metrics"]["rain_forecast_total_mm"] = weather.get("precipitation_forecast_mm")
    return merged


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _reference_time(metrics: Dict[str, Any]) -> datetime:
    """Return the recency reference timestamp for evidence age checks.

    Uses an explicit evidence_reference_time from the metrics when available
    (historical package analysis). Otherwise falls back to current UTC time so
    live and uploaded evidence are both evaluated against wall-clock age.
    The evidence timestamp itself is never used as its own reference.
    """
    explicit = _parse_time(metrics.get("evidence_reference_time"))
    return explicit if explicit is not None else datetime.now(timezone.utc)


def _hours_old(timestamp: Any, reference: datetime) -> Optional[float]:
    parsed = _parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (reference - parsed).total_seconds() / 3600)


def _flow_validation(merged: Dict[str, Any], field_block: Optional[str]) -> Tuple[Optional[float], str, List[str]]:
    metrics = merged.get("metrics", {})
    # No early-return bypass: every flow value — including pre-labeled validated_flow_m3h —
    # must pass the full recency, provenance, block, variance, and pressure gate.
    evidence = merged.get("flow_evidence") or metrics.get("flow_evidence") or {}
    flow = _first_number(
        evidence.get("value_m3h"),
        metrics.get("validated_flow_m3h"),
        metrics.get("flow_m3h"),
        metrics.get("avg_flow_m3h"),
    )
    notes: List[str] = []
    if flow is None or flow <= 0:
        return None, "unavailable", ["Validated positive flow evidence is unavailable."]

    provenance = str(evidence.get("provenance") or metrics.get("flow_provenance") or "").lower()
    if provenance not in {"controller", "controller_event", "controller-confirmed", "flow_meter", "flow-meter", "flow_meter_confirmed"}:
        notes.append("Flow evidence provenance is missing controller or flow-meter confirmation.")

    evidence_block = evidence.get("block") or metrics.get("flow_block")
    if not evidence_block or not field_block:
        notes.append("Flow evidence must identify the matching field or block.")
    elif str(evidence_block).lower() != str(field_block).lower():
        return None, "inconsistent", ["Flow evidence belongs to a different block."]

    reference = _reference_time(metrics)
    timestamp = _parse_time(evidence.get("timestamp"))
    if timestamp is None:
        notes.append("Flow evidence timestamp is unavailable.")
    valid_until = _parse_time(evidence.get("valid_until") or metrics.get("flow_valid_until"))
    max_age_hours = _first_number(evidence.get("max_age_hours"), metrics.get("flow_max_age_hours"))
    if valid_until is not None:
        if reference > valid_until:
            notes.append("Flow evidence is outside its explicit validation period.")
    elif timestamp is not None and max_age_hours is not None:
        freshness = get_scientific_tool_registry().run(
            "evidence.freshness.v1",
            {"observed_at": timestamp, "evaluated_at": reference, "max_age_hours": max_age_hours},
        )
        if freshness.status != "COMPUTED" or not freshness.output.get("fresh"):
            notes.append("Flow evidence is outside its explicit freshness requirement.")
    else:
        notes.append("Flow evidence lacks an explicit validity period or calibrated freshness requirement.")

    variance = _first_number(metrics.get("max_flow_variance_percent"), metrics.get("applied_variance_percent"))
    variance_limit = _first_number(evidence.get("max_variance_percent"), metrics.get("max_allowed_flow_variance_percent"))
    if variance is not None and variance_limit is None:
        notes.append("Observed flow variance lacks a source-specific acceptance limit.")
    elif variance is not None and variance_limit is not None and abs(variance) > variance_limit:
        return None, "inconsistent", ["Flow variance exceeds the explicit calibrated acceptance limit."]

    pressure = str(evidence.get("pressure_state") or merged.get("pressure_state") or "").lower()
    if pressure in {"severe", "critical", "low_pressure", "pressure_failure"} or evidence.get("severe_pressure_warning"):
        return None, "inconsistent", ["Severe pressure warning prevents validated flow use."]
    if pressure not in {"stable", "normal"}:
        notes.append("Flow evidence lacks a stable pressure confirmation.")

    calibration_status = str(evidence.get("calibration_status") or metrics.get("flow_calibration_status") or "").lower()
    if calibration_status not in {"validated", "calibrated", "accepted", "current"}:
        notes.append("Flow evidence lacks current calibration or validation status.")

    if notes:
        return None, "partial", notes
    return flow, "validated", []


def _recent_credit(merged: Dict[str, Any], field_block: Optional[str]) -> Tuple[Optional[float], str, List[str]]:
    metrics = merged.get("metrics", {})
    evidence = merged.get("recent_irrigation_evidence") or metrics.get("recent_irrigation_evidence") or {}
    if not isinstance(evidence, dict) or not evidence:
        return None, "unavailable", ["Recent applied-water status is unavailable."]
    depth = _first_number(evidence.get("depth_mm"), evidence.get("applied_depth_mm"), metrics.get("recent_irrigation_depth_mm"))

    evidence_block = evidence.get("block")
    if not evidence_block or not field_block:
        return None, "partial", ["Recent irrigation evidence must identify the matching field or block."]
    if str(evidence_block).lower() != str(field_block).lower():
        return None, "unavailable", ["Recent irrigation event belongs to a different block."]

    confirmation = str(evidence.get("confirmation") or evidence.get("status") or "").lower()
    if confirmation not in {"controller_confirmed", "flow_meter_confirmed", "controller-confirmed", "flow-meter-confirmed", "complete"}:
        return None, "partial", ["Recent irrigation event lacks controller or flow-meter confirmation."]

    if evidence.get("no_recent_irrigation_confirmed") is True:
        depth = 0.0
        status = "verified_none"
    elif depth is None or depth <= 0:
        return None, "unavailable", ["Recent applied-water credit is unavailable."]
    else:
        status = "verified_recent"

    reference = _reference_time(metrics)
    timestamp = _parse_time(evidence.get("timestamp"))
    if timestamp is None:
        return None, "partial", ["Recent irrigation event timestamp is unavailable."]
    valid_until = _parse_time(evidence.get("valid_until"))
    max_age_hours = _first_number(evidence.get("max_age_hours"), metrics.get("recent_irrigation_max_age_hours"))
    if valid_until is not None:
        if reference > valid_until:
            return None, "stale", ["Recent irrigation evidence is outside its explicit validity period."]
    elif max_age_hours is not None:
        freshness = get_scientific_tool_registry().run(
            "evidence.freshness.v1",
            {"observed_at": timestamp, "evaluated_at": reference, "max_age_hours": max_age_hours},
        )
        if freshness.status != "COMPUTED" or not freshness.output.get("fresh"):
            return None, "stale", ["Recent irrigation evidence is outside its explicit freshness requirement."]
    else:
        return None, "partial", ["Recent irrigation evidence lacks an explicit validity period or freshness requirement."]

    return depth, status, []


def _manual_payload_from_workbench(context: Dict[str, Any]) -> Dict[str, Any]:
    metrics = context.get("metrics", {})
    flow_rate = _first_number(metrics.get("validated_flow_m3h"), metrics.get("avg_flow_m3h"), context.get("flow_rate_m3h"))
    area = _first_number(context.get("area"), metrics.get("field_area_ha"))
    return {
        "field_id": str(context.get("block") or context.get("field_id") or "workbench-field"),
        "farm_id": context.get("farm"),
        "source": context.get("source", "mixed"),
        "source_entity_id": context.get("source_entity_id"),
        "crop_type": context.get("crop"),
        "soil_type": context.get("soil"),
        "irrigation_method": context.get("irrigation_method"),
        "area": area,
        "weather_context": {
            "eto_mm": _first_number(metrics.get("avg_eto_mm"), context.get("eto_mm")),
            "precipitation_forecast_mm": _first_number(metrics.get("rain_forecast_total_mm"), context.get("rain_forecast_mm")),
        },
        "sensor_context": {
            "moisture_percent": _first_number(metrics.get("avg_moisture_percent"), context.get("moisture_percent")),
            "pressure_kpa": _first_number(metrics.get("pressure_kpa"), context.get("pressure_kpa")),
            "flow_m3h": flow_rate,
        },
        "controller_context": {
            "provider": context.get("provider_context"),
            "online": context.get("controller_online"),
        },
        "recent_irrigation_context": {
            "last_depth_mm": _first_number(metrics.get("recent_irrigation_depth_mm"), context.get("recent_irrigation_depth_mm")),
            "events_last_7_days": metrics.get("controller_event_count"),
        },
        "field_observations": context.get("field_notes", []),
        "crop_coefficient": _first_number(context.get("crop_coefficient"), metrics.get("crop_coefficient")),
        "effective_rainfall_mm": _first_number(context.get("effective_rainfall_mm"), metrics.get("effective_rainfall_mm")),
        "root_zone_replenishment_mm": _first_number(context.get("root_zone_replenishment_mm"), metrics.get("root_zone_replenishment_mm")),
        "net_irrigation_requirement_mm": _first_number(context.get("net_irrigation_requirement_mm"), metrics.get("net_irrigation_requirement_mm")),
        "irrigation_efficiency": _first_number(context.get("irrigation_efficiency"), metrics.get("irrigation_efficiency")),
        "operating_window": context.get("operating_window"),
        "confidence_inputs": context.get("source_kinds", []),
    }


def _deficit_percent(context: Dict[str, Any]) -> Optional[float]:
    metrics = context.get("metrics", {})
    return _first_number(metrics.get("avg_deficit_percent"), context.get("soil_moisture_deficit_pct"))


def _root_zone_mm(context: Dict[str, Any]) -> Optional[float]:
    root_cm = _first_number(context.get("root_zone_depth_cm"))
    if root_cm is None:
        return _first_number(context.get("root_zone_depth_mm"))
    return root_cm * 10.0


class IrrigationDecisionOrchestrator:
    def __init__(self) -> None:
        self.intelligence = IntelligenceEngineV1()
        self.kernel = AgronomicDecisionKernelV02()

    def run(
        self,
        context: Dict[str, Any],
        *,
        mode: str,
        origin: str,
        manual_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged = _merge_context(context, manual_overrides)
        normalized = self.intelligence.normalize_field_context(_manual_payload_from_workbench(merged))
        quality = self.intelligence.evaluate_data_quality(normalized.normalized_context)
        field = normalized.normalized_context
        metrics = merged.get("metrics", {})

        flow, flow_status, flow_notes = _flow_validation(merged, field.field_id)
        recent_credit, recent_status, recent_notes = _recent_credit(merged, field.field_id)
        pressure_state = "stable"
        if metrics.get("missing_pressure_count", 0):
            pressure_state = "partial"

        missing: List[str] = list(quality.missing_inputs)
        if flow_status != "validated":
            missing.append("validated_flow_or_application_rate")
        if recent_status not in {"verified_recent", "verified_none"}:
            missing.append("recent_verified_applied_water_credit")

        decision_input = AgronomicDecisionInput(
            eto_mm=field.weather_context.eto_mm,
            crop_type=field.crop_type,
            growth_stage=merged.get("growth_stage"),
            crop_coefficient=_first_number(merged.get("crop_coefficient"), metrics.get("crop_coefficient")),
            precipitation_forecast_mm=field.weather_context.precipitation_forecast_mm,
            effective_rainfall_mm=_first_number(merged.get("effective_rainfall_mm"), metrics.get("effective_rainfall_mm")),
            soil_type=field.soil_type,
            root_zone_depth_mm=_root_zone_mm(merged),
            soil_moisture_deficit_pct=_deficit_percent(merged),
            management_allowable_depletion=_first_number(merged.get("management_allowable_depletion")),
            root_zone_replenishment_mm=_first_number(merged.get("root_zone_replenishment_mm"), metrics.get("root_zone_replenishment_mm")),
            net_irrigation_requirement_mm=_first_number(merged.get("net_irrigation_requirement_mm"), metrics.get("net_irrigation_requirement_mm")),
            recent_irrigation_depth_mm=recent_credit,
            irrigation_method=field.irrigation_method,
            irrigation_efficiency=_first_number(merged.get("irrigation_efficiency"), metrics.get("irrigation_efficiency")),
            field_area_ha=field.area,
            controller_capacity_m3h=_first_number(merged.get("controller_capacity_m3h")),
            flow_rate_m3h=flow,
            flow_validation_status=flow_status,  # type: ignore[arg-type]
            pressure_state=pressure_state,
            operating_window=merged.get("operating_window"),
            field_observations=list(field.field_observations),
            confidence_state=quality.data_quality_label,
            missing_data_state=missing,
            recent_irrigation_credit_status=recent_status,  # type: ignore[arg-type]
            recommendation_origin=origin,
        )
        decision = self.kernel.compute(decision_input)
        decision["flow_validation_notes"] = flow_notes
        decision["recent_irrigation_credit_notes"] = recent_notes

        ref_time = _reference_time(metrics)
        evaluation_mode_label = (
            "historical_package" if metrics.get("evidence_reference_time") else "current_utc"
        )
        return {
            "normalized_result": normalized,
            "data_quality": quality,
            "decision": decision,
            "manual_overrides_used": sorted((manual_overrides or {}).keys()),
            "mode": mode,
            "origin": origin,
            "evaluation_reference_time": ref_time.isoformat(),
            "evaluation_mode_label": evaluation_mode_label,
        }

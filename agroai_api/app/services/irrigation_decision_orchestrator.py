from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.agronomic_decision_kernel import AgronomicDecisionInput, AgronomicDecisionKernelV02
from app.services.intelligence_engine import IntelligenceEngineV1


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
            merged["metrics"]["validated_flow_m3h"] = sensor.get("flow_m3h")
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

        flow = field.sensor_context.flow_m3h or _first_number(metrics.get("avg_flow_m3h"), metrics.get("validated_flow_m3h"))
        pressure_state = "stable"
        if metrics.get("missing_pressure_count", 0):
            pressure_state = "partial"

        missing: List[str] = list(quality.missing_inputs)
        if flow is None:
            missing.append("validated_flow_or_application_rate")

        decision_input = AgronomicDecisionInput(
            eto_mm=field.weather_context.eto_mm,
            crop_type=field.crop_type,
            growth_stage=merged.get("growth_stage"),
            crop_coefficient=_first_number(merged.get("crop_coefficient")),
            precipitation_forecast_mm=field.weather_context.precipitation_forecast_mm,
            effective_rainfall_mm=_first_number(merged.get("effective_rainfall_mm")),
            soil_type=field.soil_type,
            root_zone_depth_mm=_root_zone_mm(merged),
            soil_moisture_deficit_pct=_deficit_percent(merged),
            management_allowable_depletion=_first_number(merged.get("management_allowable_depletion")),
            recent_irrigation_depth_mm=field.recent_irrigation_context.last_depth_mm,
            irrigation_method=field.irrigation_method,
            irrigation_efficiency=_first_number(merged.get("irrigation_efficiency")),
            field_area_ha=field.area,
            controller_capacity_m3h=_first_number(merged.get("controller_capacity_m3h")),
            flow_rate_m3h=flow,
            pressure_state=pressure_state,
            operating_window=merged.get("operating_window"),
            field_observations=list(field.field_observations),
            confidence_state=quality.data_quality_label,
            missing_data_state=missing,
            recommendation_origin=origin,
        )
        decision = self.kernel.compute(decision_input)

        return {
            "normalized_result": normalized,
            "data_quality": quality,
            "decision": decision,
            "manual_overrides_used": sorted((manual_overrides or {}).keys()),
            "mode": mode,
            "origin": origin,
        }

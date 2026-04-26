"""AGRO-AI Intelligence Engine v1.

Source-aware, data-quality-aware irrigation recommendations with graceful degradation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

SupportedLanguage = Literal["en", "fr", "es", "pt", "ar"]
DataQualityLabel = Literal["full_telemetry", "partial_telemetry", "manual_only", "weather_only", "insufficient"]
RecommendationAction = Literal["irrigate", "wait", "inspect", "insufficient_data"]


class LocationContext(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    region: Optional[str] = None
    country: Optional[str] = None
    county: Optional[str] = None


class WeatherContext(BaseModel):
    eto_mm: Optional[float] = None
    precipitation_forecast_mm: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_kph: Optional[float] = None


class SensorContext(BaseModel):
    moisture_percent: Optional[float] = None
    pressure_kpa: Optional[float] = None
    flow_m3h: Optional[float] = None
    captured_at: Optional[datetime] = None


class ControllerContext(BaseModel):
    provider: Optional[str] = None
    online: Optional[bool] = None
    last_seen_at: Optional[datetime] = None


class RecentIrrigationContext(BaseModel):
    last_irrigation_at: Optional[datetime] = None
    last_duration_minutes: Optional[float] = None
    last_depth_mm: Optional[float] = None
    events_last_7_days: Optional[int] = None


class CanonicalFieldContext(BaseModel):
    field_id: str
    farm_id: Optional[str] = None
    source: Literal["wiseconn", "talgil", "manual", "mixed", "unknown"] = "unknown"
    source_entity_id: Optional[str] = None
    crop_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    soil_type: Optional[str] = None
    area: Optional[float] = Field(default=None, description="Area in hectares unless units override")
    location: LocationContext = Field(default_factory=LocationContext)
    weather_context: WeatherContext = Field(default_factory=WeatherContext)
    sensor_context: SensorContext = Field(default_factory=SensorContext)
    controller_context: ControllerContext = Field(default_factory=ControllerContext)
    recent_irrigation_context: RecentIrrigationContext = Field(default_factory=RecentIrrigationContext)
    field_observations: List[str] = Field(default_factory=list)
    data_quality_score: Optional[int] = None
    missing_inputs: List[str] = Field(default_factory=list)
    confidence_inputs: List[str] = Field(default_factory=list)


class ContextNormalizationResult(BaseModel):
    normalized_context: CanonicalFieldContext
    aliases_applied: Dict[str, str]
    ignored_fields: List[str]
    warnings: List[str]


class DataQualityResult(BaseModel):
    data_quality_score: int
    data_quality_label: DataQualityLabel
    missing_inputs: List[str]
    recommendation_limitations: List[str]
    next_best_data_to_collect: List[str]


class ExplainabilityResult(BaseModel):
    why: str
    key_drivers: List[str]
    missing_data: List[str]
    what_could_change: List[str]
    verify_after_action: List[str]


class ExecutionTask(BaseModel):
    task_title: str
    task_steps: List[str]
    due_window: str
    assigned_role: str
    confirmation_needed: bool
    verification_method: str


class VerificationPlan(BaseModel):
    recommended_action: str
    schedule_to_apply: str
    confirmation_to_collect: str
    expected_field_outcome: str
    warning_trigger: str


class RecommendationRequest(BaseModel):
    field_context: CanonicalFieldContext
    language: SupportedLanguage = "en"
    user_role: Optional[str] = None
    units: Optional[str] = None
    time_horizon: str = "today"


class RecommendationResponse(BaseModel):
    recommendation_id: str
    action: RecommendationAction
    recommended_timing: Optional[str] = None
    recommended_duration_minutes: Optional[float] = None
    recommended_depth_mm: Optional[float] = None
    priority: Literal["low", "medium", "high"]
    confidence_score: int
    confidence_label: Literal["low", "moderate", "high"]
    reasoning_summary: str
    key_drivers: List[str]
    risk_flags: List[str]
    missing_data: List[str]
    verification_required: bool
    human_readable_explanation: Dict[str, str]
    language_status: str
    machine_readable_decision: Dict[str, Any]
    source_trace: Dict[str, Any]
    data_quality: DataQualityResult
    execution_task: ExecutionTask
    verification_plan: VerificationPlan


_ALLOWED_TOP_LEVEL_FIELDS = {
    "field_id",
    "farm_id",
    "source",
    "source_entity_id",
    "crop_type",
    "irrigation_method",
    "soil_type",
    "area",
    "location",
    "weather_context",
    "sensor_context",
    "controller_context",
    "recent_irrigation_context",
    "field_observations",
    "data_quality_score",
    "missing_inputs",
    "confidence_inputs",
}


class IntelligenceEngineV1:
    def _float_if_numeric(self, value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_weather(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
        aliases_applied: Dict[str, str] = {}
        ignored: List[str] = []
        warnings: List[str] = []

        weather = dict(payload.get("weather_context") or {})
        weather_aliases = {
            "rain_forecast_mm": "precipitation_forecast_mm",
            "rainfall_forecast_mm": "precipitation_forecast_mm",
            "forecast_rain_mm": "precipitation_forecast_mm",
            "evapotranspiration_mm": "eto_mm",
            "et_mm": "eto_mm",
            "et0_mm": "eto_mm",
        }

        for alias, canonical in weather_aliases.items():
            if alias in payload and canonical not in weather:
                weather[canonical] = payload[alias]
                aliases_applied[f"{alias}"] = f"weather_context.{canonical}"
            if alias in weather and canonical not in weather:
                weather[canonical] = weather[alias]
                aliases_applied[f"weather_context.{alias}"] = f"weather_context.{canonical}"

        payload["weather_context"] = weather
        return payload, aliases_applied, ignored, warnings

    def _normalize_location(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
        aliases_applied: Dict[str, str] = {}
        ignored: List[str] = []
        warnings: List[str] = []

        location = dict(payload.get("location") or {})

        if "country" in payload and "country" not in location:
            location["country"] = payload["country"]
            aliases_applied["country"] = "location.country"
        if "state" in payload and "region" not in location:
            location["region"] = payload["state"]
            aliases_applied["state"] = "location.region"
        if "province" in payload and "region" not in location:
            location["region"] = payload["province"]
            aliases_applied["province"] = "location.region"
        if "county" in payload and "county" not in location:
            location["county"] = payload["county"]
            aliases_applied["county"] = "location.county"
        if "latitude" in payload and "lat" not in location:
            location["lat"] = payload["latitude"]
            aliases_applied["latitude"] = "location.lat"
        if "longitude" in payload and "lon" not in location:
            location["lon"] = payload["longitude"]
            aliases_applied["longitude"] = "location.lon"

        if "state" in location and "region" not in location:
            location["region"] = location["state"]
            aliases_applied["location.state"] = "location.region"
        if "province" in location and "region" not in location:
            location["region"] = location["province"]
            aliases_applied["location.province"] = "location.region"
        if "latitude" in location and "lat" not in location:
            location["lat"] = location["latitude"]
            aliases_applied["location.latitude"] = "location.lat"
        if "longitude" in location and "lon" not in location:
            location["lon"] = location["longitude"]
            aliases_applied["location.longitude"] = "location.lon"

        payload["location"] = location
        return payload, aliases_applied, ignored, warnings

    def _normalize_recent_irrigation(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
        aliases_applied: Dict[str, str] = {}
        ignored: List[str] = []
        warnings: List[str] = []

        recent = dict(payload.get("recent_irrigation_context") or {})

        def use(alias: str, canonical: str):
            if alias in payload and canonical not in recent:
                recent[canonical] = payload[alias]
                aliases_applied[alias] = f"recent_irrigation_context.{canonical}"
            if alias in recent and canonical not in recent:
                recent[canonical] = recent[alias]
                aliases_applied[f"recent_irrigation_context.{alias}"] = f"recent_irrigation_context.{canonical}"

        use("last_irrigation_duration_minutes", "last_duration_minutes")
        use("last_irrigation_depth_mm", "last_depth_mm")
        use("irrigations_last_7_days", "events_last_7_days")

        hours_ago = payload.get("last_irrigation_hours_ago", recent.get("last_irrigation_hours_ago"))
        days_ago = payload.get("last_irrigation_days_ago", recent.get("last_irrigation_days_ago"))

        if hours_ago is not None and "last_irrigation_at" not in recent:
            h = self._float_if_numeric(hours_ago)
            if h is not None:
                recent["last_irrigation_at"] = (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()
                aliases_applied["last_irrigation_hours_ago"] = "recent_irrigation_context.last_irrigation_at"
            else:
                warnings.append("last_irrigation_hours_ago ignored because value is not numeric")

        if days_ago is not None and "last_irrigation_at" not in recent:
            d = self._float_if_numeric(days_ago)
            if d is not None:
                recent["last_irrigation_at"] = (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()
                aliases_applied["last_irrigation_days_ago"] = "recent_irrigation_context.last_irrigation_at"
            else:
                warnings.append("last_irrigation_days_ago ignored because value is not numeric")

        payload["recent_irrigation_context"] = recent
        return payload, aliases_applied, ignored, warnings

    def _normalize_sensor_context(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
        aliases_applied: Dict[str, str] = {}
        ignored: List[str] = []
        warnings: List[str] = []

        sensor = dict(payload.get("sensor_context") or {})

        sensor_aliases = {
            "soil_moisture_percent": "moisture_percent",
            "moisture_pct": "moisture_percent",
        }

        for alias, canonical in sensor_aliases.items():
            if alias in payload and canonical not in sensor:
                sensor[canonical] = payload[alias]
                aliases_applied[alias] = f"sensor_context.{canonical}"
            if alias in sensor and canonical not in sensor:
                sensor[canonical] = sensor[alias]
                aliases_applied[f"sensor_context.{alias}"] = f"sensor_context.{canonical}"

        pressure_value = payload.get("pressure", sensor.get("pressure"))
        if pressure_value is not None and "pressure_kpa" not in sensor:
            n = self._float_if_numeric(pressure_value)
            if n is not None:
                sensor["pressure_kpa"] = n
                aliases_applied["pressure"] = "sensor_context.pressure_kpa"
            else:
                warnings.append("pressure ignored because value is not numeric")

        flow_value = payload.get("flow_rate", sensor.get("flow_rate"))
        if flow_value is not None and "flow_m3h" not in sensor:
            n = self._float_if_numeric(flow_value)
            if n is not None:
                sensor["flow_m3h"] = n
                aliases_applied["flow_rate"] = "sensor_context.flow_m3h"
            else:
                warnings.append("flow_rate ignored because value is not numeric")

        payload["sensor_context"] = sensor
        return payload, aliases_applied, ignored, warnings

    def normalize_field_context(self, payload: Dict[str, Any]) -> ContextNormalizationResult:
        working = dict(payload)
        aliases_applied: Dict[str, str] = {}
        warnings: List[str] = []

        for normalizer in (
            self._normalize_weather,
            self._normalize_location,
            self._normalize_recent_irrigation,
            self._normalize_sensor_context,
        ):
            working, applied, _, w = normalizer(working)
            aliases_applied.update(applied)
            warnings.extend(w)

        ignored_fields = sorted(
            key for key in working.keys() if key not in _ALLOWED_TOP_LEVEL_FIELDS and key not in aliases_applied
        )

        canonical_payload = {k: v for k, v in working.items() if k in _ALLOWED_TOP_LEVEL_FIELDS}
        normalized = CanonicalFieldContext(**canonical_payload)

        return ContextNormalizationResult(
            normalized_context=normalized,
            aliases_applied=aliases_applied,
            ignored_fields=ignored_fields,
            warnings=warnings,
        )

    def evaluate_data_quality(self, field: CanonicalFieldContext) -> DataQualityResult:
        missing: List[str] = []
        limitations: List[str] = []
        next_data: List[str] = []

        has_sensors = field.sensor_context.moisture_percent is not None or field.sensor_context.flow_m3h is not None
        has_controller = field.controller_context.provider is not None
        has_weather = field.weather_context.eto_mm is not None or field.weather_context.precipitation_forecast_mm is not None
        has_manual = bool(field.field_observations) or field.recent_irrigation_context.last_depth_mm is not None

        if not field.crop_type:
            missing.append("crop_type")
            next_data.append("Set crop type for evapotranspiration sensitivity.")
        if not field.soil_type:
            missing.append("soil_type")
            next_data.append("Set soil type to estimate infiltration and holding capacity.")
        if field.area is None:
            missing.append("area")
            next_data.append("Provide field area for volume-level planning.")
        if not has_weather:
            missing.append("weather_context")
            next_data.append("Add 48-hour weather forecast and ETo.")

        score = 25
        if has_weather:
            score += 20
        if has_manual:
            score += 15
        if has_controller:
            score += 15
        if has_sensors:
            score += 20
        if field.crop_type:
            score += 3
        if field.soil_type:
            score += 2

        score = max(0, min(score, 100))

        if has_sensors and has_weather and field.crop_type and field.soil_type:
            label: DataQualityLabel = "full_telemetry"
        elif has_controller or has_sensors:
            label = "partial_telemetry"
        elif has_manual and has_weather:
            label = "manual_only"
        elif has_weather:
            label = "weather_only"
        else:
            label = "insufficient"

        if label in ("manual_only", "weather_only", "insufficient"):
            limitations.append("No live zone telemetry; recommendation uses conservative safety margins.")
        if "crop_type" in missing:
            limitations.append("Crop-specific water demand cannot be calibrated.")
        if "soil_type" in missing:
            limitations.append("Soil storage assumptions are generic; infiltration risk is uncertain.")

        return DataQualityResult(
            data_quality_score=score,
            data_quality_label=label,
            missing_inputs=missing,
            recommendation_limitations=limitations,
            next_best_data_to_collect=next_data,
        )

    def build_explainability(
        self,
        field: CanonicalFieldContext,
        quality: DataQualityResult,
        action: RecommendationAction,
        depth_mm: Optional[float],
    ) -> ExplainabilityResult:
        drivers: List[str] = []
        if field.weather_context.eto_mm is not None:
            drivers.append(f"ETo={field.weather_context.eto_mm:.1f} mm/day")
        if field.weather_context.precipitation_forecast_mm is not None:
            drivers.append(f"Forecast rain={field.weather_context.precipitation_forecast_mm:.1f} mm")
        if field.sensor_context.moisture_percent is not None:
            drivers.append(f"Soil moisture={field.sensor_context.moisture_percent:.1f}%")
        if field.recent_irrigation_context.last_depth_mm is not None:
            drivers.append(f"Last irrigation depth={field.recent_irrigation_context.last_depth_mm:.1f} mm")

        why = (
            f"Action '{action}' chosen using {quality.data_quality_label} evidence"
            + (f" with target depth {depth_mm:.1f} mm." if depth_mm is not None else ".")
        )
        what_changes = [
            "Higher rainfall forecast could shift decision to wait.",
            "Low moisture verification could shift decision to irrigate sooner.",
        ]
        verify = [
            "Confirm irrigation execution in controller or manual log.",
            "Re-check soil condition within 12-24h.",
        ]

        return ExplainabilityResult(
            why=why,
            key_drivers=drivers,
            missing_data=quality.missing_inputs,
            what_could_change=what_changes,
            verify_after_action=verify,
        )

    def recommend(self, request: RecommendationRequest) -> RecommendationResponse:
        field = request.field_context
        quality = self.evaluate_data_quality(field)

        eto = field.weather_context.eto_mm or 0.0
        rain = field.weather_context.precipitation_forecast_mm or 0.0
        moisture = field.sensor_context.moisture_percent

        base_need_mm = max(0.0, eto * 1.15 - rain)
        conservative_mm = min(base_need_mm, 8.0)
        action: RecommendationAction = "wait"
        duration: Optional[float] = None
        depth: Optional[float] = None
        risk_flags: List[str] = []

        if quality.data_quality_label == "insufficient":
            action = "insufficient_data"
            risk_flags.append("critical_data_missing")
        elif moisture is not None and moisture < 24:
            action = "irrigate"
            depth = round(max(conservative_mm, 6.0), 1)
        elif moisture is not None and moisture > 36:
            action = "wait"
        elif base_need_mm >= 5:
            action = "irrigate" if quality.data_quality_score >= 60 else "inspect"
            depth = round(conservative_mm, 1) if action == "irrigate" else None
        elif rain >= 3:
            action = "wait"
        elif quality.data_quality_score < 55:
            action = "inspect"
        else:
            action = "wait"

        if action == "irrigate" and depth is not None:
            method_factor = 1.0
            if (field.irrigation_method or "").lower() in {"drip", "micro"}:
                method_factor = 0.8
            duration = round(depth * 12 * method_factor, 1)

        confidence_score = max(20, min(98, quality.data_quality_score - (10 if action == "inspect" else 0)))
        if action == "insufficient_data":
            confidence_score = min(confidence_score, 35)
        confidence_label = "high" if confidence_score >= 75 else "moderate" if confidence_score >= 50 else "low"

        if confidence_label == "low":
            risk_flags.append("low_confidence")
        if "soil_type" in quality.missing_inputs:
            risk_flags.append("soil_uncertainty")
        if "crop_type" in quality.missing_inputs:
            risk_flags.append("crop_demand_unknown")

        explain = self.build_explainability(field, quality, action, depth)

        language_status = "en_ready" if request.language == "en" else f"fallback_to_en:{request.language}"

        timing = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        recommended_timing = timing.isoformat()
        if action in {"wait", "insufficient_data"}:
            recommended_timing = (timing + timedelta(hours=8)).isoformat()

        execution_task = ExecutionTask(
            task_title=(
                "Apply conservative irrigation pulse" if action == "irrigate" else "Inspect field moisture and irrigation readiness"
            ),
            task_steps=(
                [
                    "Validate valve/line availability.",
                    f"Run irrigation for {duration or 0} minutes.",
                    "Record applied duration and estimated depth.",
                ]
                if action == "irrigate"
                else [
                    "Visit field and inspect soil moisture at root depth.",
                    "Check controller connectivity or manual readiness.",
                    "Log observation before next recommendation cycle.",
                ]
            ),
            due_window="within_6h" if action == "irrigate" else "today",
            assigned_role=request.user_role or "farm_manager",
            confirmation_needed=True,
            verification_method="controller_log_or_manual_confirmation",
        )

        verification_plan = VerificationPlan(
            recommended_action=action,
            schedule_to_apply=(f"{duration} min irrigation pulse" if duration is not None else "No irrigation schedule to apply"),
            confirmation_to_collect="Execution confirmation from controller event or signed manual log.",
            expected_field_outcome="Stable moisture trend and no visible stress over next 24h.",
            warning_trigger="If moisture declines or stress signs persist, raise warning and re-evaluate.",
        )

        recommendation_id = f"rec_{uuid.uuid4().hex[:12]}"

        return RecommendationResponse(
            recommendation_id=recommendation_id,
            action=action,
            recommended_timing=recommended_timing,
            recommended_duration_minutes=duration,
            recommended_depth_mm=depth,
            priority="high" if action == "irrigate" else "medium" if action == "inspect" else "low",
            confidence_score=confidence_score,
            confidence_label=confidence_label,
            reasoning_summary=explain.why,
            key_drivers=explain.key_drivers,
            risk_flags=risk_flags,
            missing_data=quality.missing_inputs,
            verification_required=True,
            human_readable_explanation={
                "en": f"Decision: {action}. Confidence {confidence_label} ({confidence_score}/100). Reason: {explain.why}"
            },
            language_status=language_status,
            machine_readable_decision={
                "action": action,
                "timing": recommended_timing,
                "duration_minutes": duration,
                "depth_mm": depth,
                "quality_score": quality.data_quality_score,
            },
            source_trace={
                "source": field.source,
                "source_entity_id": field.source_entity_id,
                "inputs_used": field.confidence_inputs,
                "missing_inputs": quality.missing_inputs,
                "telemetry_used": quality.data_quality_label in {"full_telemetry", "partial_telemetry"},
            },
            data_quality=quality,
            execution_task=execution_task,
            verification_plan=verification_plan,
        )

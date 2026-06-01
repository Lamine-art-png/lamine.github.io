from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from app.services.calibration_packs import (
    CALIBRATION_PACK_VERSION,
    resolve_calibration,
)

DecisionAction = Literal["irrigate", "wait", "inspect", "insufficient_data"]


def _num(value: Any) -> Optional[float]:
    try:
        if value in ("", None, "not available", "provider context pending"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class AgronomicDecisionInput:
    eto_mm: Optional[float] = None
    crop_type: Optional[str] = None
    growth_stage: Optional[str] = None
    crop_coefficient: Optional[float] = None
    precipitation_forecast_mm: Optional[float] = None
    effective_rainfall_mm: Optional[float] = None
    soil_type: Optional[str] = None
    root_zone_depth_mm: Optional[float] = None
    soil_moisture_deficit_pct: Optional[float] = None
    management_allowable_depletion: Optional[float] = None
    recent_irrigation_depth_mm: Optional[float] = None
    irrigation_method: Optional[str] = None
    irrigation_efficiency: Optional[float] = None
    field_area_ha: Optional[float] = None
    controller_capacity_m3h: Optional[float] = None
    flow_rate_m3h: Optional[float] = None
    pressure_state: Optional[str] = None
    operating_window: Optional[str] = None
    field_observations: List[str] = field(default_factory=list)
    confidence_state: Optional[str] = None
    missing_data_state: List[str] = field(default_factory=list)
    recommendation_origin: str = "deterministic_engine"


class AgronomicDecisionKernelV02:
    version = "agronomic_decision_kernel_v0.2"

    def compute(self, payload: AgronomicDecisionInput | Dict[str, Any]) -> Dict[str, Any]:
        data = payload if isinstance(payload, AgronomicDecisionInput) else AgronomicDecisionInput(**payload)
        has_weather = data.eto_mm is not None
        calibration = resolve_calibration(data.crop_type, data.soil_type, data.irrigation_method, has_weather)

        crop = calibration["crop"]
        soil = calibration["soil"]
        method = calibration["irrigation"]
        assumptions_used = list(calibration["assumptions_used"])

        kc = data.crop_coefficient if data.crop_coefficient is not None else crop.crop_coefficient
        root_zone_mm = data.root_zone_depth_mm if data.root_zone_depth_mm is not None else crop.root_zone_depth_mm
        mad = (
            data.management_allowable_depletion
            if data.management_allowable_depletion is not None
            else crop.management_allowable_depletion
        )
        efficiency = data.irrigation_efficiency if data.irrigation_efficiency is not None else method.efficiency
        effective_rain = (
            data.effective_rainfall_mm
            if data.effective_rainfall_mm is not None
            else min(data.precipitation_forecast_mm or 0.0, (data.precipitation_forecast_mm or 0.0) * 0.8)
        )
        recent_credit = min(data.recent_irrigation_depth_mm or 0.0, 12.0)

        missing_inputs: List[str] = list(dict.fromkeys(data.missing_data_state))
        for key, value in [
            ("eto_mm", data.eto_mm),
            ("crop_type", data.crop_type),
            ("soil_type", data.soil_type),
            ("irrigation_method", data.irrigation_method),
            ("field_area_ha", data.field_area_ha),
        ]:
            if value in (None, "", "not available", "provider context pending"):
                missing_inputs.append(key)

        crop_demand = None if data.eto_mm is None else max(data.eto_mm * kc, 0.0)
        available_water = soil.available_water_mm_per_m * (root_zone_mm / 1000.0)
        validated_replenishment = 0.0
        if data.soil_moisture_deficit_pct is not None and data.soil_moisture_deficit_pct > mad * 100:
            excess_deficit = (data.soil_moisture_deficit_pct / 100.0) - mad
            validated_replenishment = min(excess_deficit * available_water, available_water * 0.35)

        net_need = None
        gross_need = None
        required_volume = None
        duration_min = None
        duration_basis = "Duration withheld until validated flow or application-rate evidence exists."

        if crop_demand is not None:
            net_need = max(crop_demand - effective_rain + validated_replenishment - recent_credit, 0.0)
            if net_need < 1.0:
                net_need = 0.0
            gross_need = net_need / efficiency if efficiency > 0 else None

        if gross_need is not None and data.field_area_ha is not None:
            required_volume = gross_need * data.field_area_ha * 10.0

        validated_flow = data.flow_rate_m3h or data.controller_capacity_m3h
        if required_volume is not None and validated_flow and validated_flow > 0:
            duration_min = (required_volume / validated_flow) * 60.0
            duration_basis = "Duration computed from required volume and validated system flow."

        if crop_demand is None:
            action: DecisionAction = "insufficient_data"
        elif missing_inputs and len(missing_inputs) >= 4:
            action = "insufficient_data"
        elif data.precipitation_forecast_mm is not None and data.precipitation_forecast_mm >= crop_demand * 0.75:
            action = "wait"
        elif net_need is not None and net_need >= 3.0:
            action = "irrigate" if (required_volume is not None or validated_replenishment > 0) else "inspect"
        elif data.soil_moisture_deficit_pct is not None and data.soil_moisture_deficit_pct >= mad * 100:
            action = "inspect"
        else:
            action = "wait"

        if action == "irrigate" and duration_min is None:
            action = "inspect"

        if action == "insufficient_data":
            recommended = "Decision pending source review"
        elif action == "inspect":
            recommended = "Inspect and collect required evidence"
        elif action == "wait":
            recommended = "Wait and monitor forecast"
        else:
            recommended = "Irrigate in approved operating window"

        completeness = 100 - min(65, len(set(missing_inputs)) * 9 + len(assumptions_used) * 5)
        if calibration["status"] == "insufficient_context":
            completeness = min(completeness, 45)
        confidence = "high" if completeness >= 82 else "moderate" if completeness >= 62 else "low"

        limitations = []
        if duration_min is None:
            limitations.append(duration_basis)
        if assumptions_used:
            limitations.append("Calibration defaults are transparent v0.2 defaults, not farm-specific calibration.")
        if data.pressure_state and data.pressure_state not in {"stable", "normal"}:
            limitations.append(f"Pressure state requires review: {data.pressure_state}.")

        calculation_trace = {
            "crop_demand_mm": crop_demand,
            "formula_crop_demand": "ETo * crop coefficient",
            "effective_rainfall_mm": effective_rain,
            "validated_root_zone_replenishment_mm": validated_replenishment,
            "recent_verified_irrigation_credit_mm": recent_credit,
            "net_irrigation_need_mm": net_need,
            "formula_net_need": "crop demand - effective rainfall + validated replenishment - recent verified irrigation credit",
            "gross_irrigation_need_mm": gross_need,
            "formula_gross_need": "net irrigation need / irrigation efficiency",
            "required_volume_m3": required_volume,
            "formula_volume": "gross irrigation depth * field area",
            "duration_minutes": duration_min,
            "formula_duration": "required volume / validated system flow",
        }

        return {
            "action": action,
            "recommended_action": recommended,
            "net_irrigation_depth_mm": round(net_need, 2) if net_need is not None else None,
            "gross_irrigation_depth_mm": round(gross_need, 2) if gross_need is not None else None,
            "estimated_volume_m3": round(required_volume, 2) if required_volume is not None else None,
            "duration_minutes": round(duration_min, 1) if duration_min is not None else None,
            "timing_window": data.operating_window or ("Tonight after 21:00 local" if action == "irrigate" else "Review within 24 hours"),
            "confidence": confidence,
            "confidence_score": completeness,
            "evidence_completeness": f"{completeness}%",
            "key_drivers": [
                f"Crop demand {crop_demand:.1f} mm" if crop_demand is not None else "ETo missing",
                f"Effective rainfall {effective_rain:.1f} mm",
                f"Root-zone replenishment {validated_replenishment:.1f} mm",
                f"Irrigation efficiency {efficiency:.2f}",
            ],
            "assumptions": assumptions_used,
            "limitations": limitations,
            "missing_inputs": sorted(set(missing_inputs)),
            "verification_requirements": [
                "Approve the schedule before controller execution.",
                "Confirm applied water from controller or flow-meter evidence.",
                "Record field observation within 24 hours.",
                "Verify outcome against source records and field response.",
            ],
            "calculation_trace": calculation_trace,
            "calibration_status": calibration["status"],
            "calibration_pack_version": CALIBRATION_PACK_VERSION,
            "recommendation_origin": data.recommendation_origin,
            "duration_basis": duration_basis,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from app.services.scientific_tool_registry import ScientificToolResult, get_scientific_tool_registry


DecisionAction = Literal["irrigate", "wait", "inspect", "insufficient_data"]
FlowValidationStatus = Literal["validated", "partial", "unavailable", "inconsistent"]
RecentIrrigationCreditStatus = Literal["verified_recent", "verified_none", "stale", "partial", "unavailable"]

KERNEL_VERSION = "agronomic_decision_kernel_v0.3"
LEGACY_CALIBRATION_PACK_VERSION = "agroai_calibration_pack_v0.2-isolated"


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
    root_zone_replenishment_mm: Optional[float] = None
    net_irrigation_requirement_mm: Optional[float] = None
    recent_irrigation_depth_mm: Optional[float] = None
    irrigation_method: Optional[str] = None
    irrigation_efficiency: Optional[float] = None
    field_area_ha: Optional[float] = None
    controller_capacity_m3h: Optional[float] = None
    flow_rate_m3h: Optional[float] = None
    flow_validation_status: FlowValidationStatus = "unavailable"
    pressure_state: Optional[str] = None
    operating_window: Optional[str] = None
    field_observations: List[str] = field(default_factory=list)
    confidence_state: Optional[str] = None
    missing_data_state: List[str] = field(default_factory=list)
    recent_irrigation_credit_status: RecentIrrigationCreditStatus = "unavailable"
    recommendation_origin: str = "deterministic_engine"


def _validated(
    value: Optional[float],
    name: str,
    warnings: list[str],
    *,
    positive: bool = False,
    fraction: bool = False,
) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append(f"{name} is not a valid numeric input and was withheld.")
        return None
    number = float(value)
    if not number == number or number in {float("inf"), float("-inf")}:
        warnings.append(f"{name} is not finite and was withheld.")
        return None
    if (positive and number <= 0) or (not positive and number < 0):
        warnings.append(f"{name} is outside its valid non-negative range and was withheld.")
        return None
    if fraction and not 0 < number <= 1:
        warnings.append(f"{name} must be an explicit fraction greater than zero and no more than one.")
        return None
    return number


def _computed(result: ScientificToolResult, key: str) -> Optional[float]:
    if result.status != "COMPUTED":
        return None
    value = result.output.get(key)
    return float(value) if isinstance(value, (int, float)) else None


class AgronomicDecisionKernelV02:
    """Compatibility name for the fail-closed v0.3 decision kernel.

    The class name remains stable for API/import compatibility.  The old v0.2
    crop/soil/method defaults are deliberately isolated and never used to emit
    an operational depth, volume, runtime, timing, or irrigation action.
    """

    version = KERNEL_VERSION

    def compute(self, payload: AgronomicDecisionInput | Dict[str, Any]) -> Dict[str, Any]:
        data = payload if isinstance(payload, AgronomicDecisionInput) else AgronomicDecisionInput(**payload)
        tools = get_scientific_tool_registry()
        warnings: list[str] = []
        missing: list[str] = list(dict.fromkeys(data.missing_data_state))

        eto = _validated(data.eto_mm, "eto_mm", warnings)
        kc = _validated(data.crop_coefficient, "crop_coefficient", warnings, positive=True)
        effective_rain = _validated(data.effective_rainfall_mm, "effective_rainfall_mm", warnings)
        replenishment = _validated(data.root_zone_replenishment_mm, "root_zone_replenishment_mm", warnings)
        explicit_net = _validated(data.net_irrigation_requirement_mm, "net_irrigation_requirement_mm", warnings)
        recent_depth = _validated(data.recent_irrigation_depth_mm, "recent_irrigation_depth_mm", warnings)
        efficiency = _validated(data.irrigation_efficiency, "irrigation_efficiency", warnings, fraction=True)
        area = _validated(data.field_area_ha, "field_area_ha", warnings, positive=True)
        flow = _validated(data.flow_rate_m3h, "flow_rate_m3h", warnings, positive=True)
        controller_capacity = _validated(data.controller_capacity_m3h, "controller_capacity_m3h", warnings, positive=True)

        tool_results: list[ScientificToolResult] = []
        etc_result = tools.run("fao56.etc.single_kc.v1", {"eto_mm": eto, "kc": kc})
        tool_results.append(etc_result)
        crop_demand = _computed(etc_result, "etc_mm")

        recent_credit: Optional[float]
        if data.recent_irrigation_credit_status == "verified_none":
            recent_credit = 0.0
        elif data.recent_irrigation_credit_status == "verified_recent" and recent_depth is not None:
            recent_credit = recent_depth
        else:
            recent_credit = None

        net_need = explicit_net
        net_basis = "explicit_net_irrigation_requirement"
        if net_need is None:
            net_basis = "derived_from_explicit_water_balance_inputs"
            requirements = {
                "eto_mm": eto,
                "crop_coefficient": kc,
                "effective_rainfall_mm": effective_rain,
                "root_zone_replenishment_mm": replenishment,
                "verified_recent_irrigation_status": recent_credit,
            }
            for name, value in requirements.items():
                if value is None:
                    missing.append(name)
            if all(value is not None for value in requirements.values()):
                net_need = max(float(crop_demand or 0.0) - float(effective_rain) + float(replenishment) - float(recent_credit), 0.0)

        if not data.crop_type:
            missing.append("crop_type")
        if not data.irrigation_method:
            missing.append("irrigation_method")
        if efficiency is None:
            missing.append("irrigation_efficiency")
        if area is None:
            missing.append("field_area_ha")
        if data.flow_validation_status != "validated":
            missing.append("validated_flow_or_application_rate")
        if not data.operating_window:
            missing.append("approved_operating_window")

        gross_result = tools.run(
            "irrigation.gross_requirement.v1",
            {"net_requirement_mm": net_need, "efficiency": efficiency},
        )
        tool_results.append(gross_result)
        gross_need = _computed(gross_result, "gross_requirement_mm")

        volume_result = tools.run(
            "irrigation.volume_from_depth.v1",
            {"depth_mm": gross_need, "area_ha": area},
        )
        tool_results.append(volume_result)
        required_volume = _computed(volume_result, "volume_m3")

        validated_flow = flow or controller_capacity
        if data.flow_validation_status != "validated":
            validated_flow = None
        duration_result = tools.run(
            "irrigation.duration_from_validated_flow.v1",
            {"required_volume_m3": required_volume, "validated_flow_m3h": validated_flow},
        )
        tool_results.append(duration_result)
        duration_min = _computed(duration_result, "duration_minutes")

        identity_ready = bool(data.crop_type and data.irrigation_method)
        operating_ready = bool(
            identity_ready
            and net_need is not None
            and gross_need is not None
            and required_volume is not None
            and duration_min is not None
            and data.operating_window
        )
        if net_need is None:
            action: DecisionAction = "insufficient_data"
            decision_status = "insufficient_data"
            recommended = "Decision pending source review"
        elif net_need == 0:
            action = "wait"
            decision_status = "supported_no_irrigation_requirement"
            recommended = "No irrigation requirement is supported by the supplied water-balance inputs"
        elif operating_ready:
            action = "irrigate"
            decision_status = "ready_for_human_approval"
            recommended = "Irrigate only after human approval in the supplied operating window"
        else:
            action = "inspect"
            decision_status = "decision_pending_source_review"
            recommended = "Inspect and collect required evidence"

        unique_missing = sorted(set(missing))
        declared_requirements = {
            "crop_or_requirement": bool(data.crop_type and (explicit_net is not None or (eto is not None and kc is not None))),
            "water_balance": explicit_net is not None or all(
                value is not None for value in (crop_demand, effective_rain, replenishment, recent_credit)
            ),
            "efficiency": efficiency is not None,
            "area": area is not None,
            "validated_flow": validated_flow is not None,
            "operating_window": bool(data.operating_window),
        }
        completeness = round(sum(1 for value in declared_requirements.values() if value) / len(declared_requirements) * 100)
        if operating_ready:
            confidence = "high"
        elif net_need is not None and gross_need is not None:
            confidence = "moderate"
        else:
            confidence = "low"

        limitations = [f"Missing required evidence: {name}." for name in unique_missing]
        limitations.extend(warnings)
        if data.pressure_state and data.pressure_state not in {"stable", "normal"}:
            limitations.append(f"Pressure state requires review: {data.pressure_state}.")
        if action != "irrigate":
            limitations.append("No executable irrigation schedule is authorized by this result.")

        key_drivers: list[str] = []
        if crop_demand is not None:
            key_drivers.append(f"ETc {crop_demand:.3f} mm from fao56.etc.single_kc.v1")
        if net_need is not None:
            key_drivers.append(f"Net requirement {net_need:.3f} mm from {net_basis}")
        if gross_need is not None:
            key_drivers.append(f"Gross requirement {gross_need:.3f} mm from irrigation.gross_requirement.v1")
        if duration_min is not None:
            key_drivers.append("Runtime computed from required volume and validated flow")

        calculation_trace = {
            "kernel_version": self.version,
            "net_requirement_basis": net_basis if net_need is not None else None,
            "crop_demand_mm": crop_demand,
            "net_irrigation_need_mm": net_need,
            "gross_irrigation_need_mm": gross_need,
            "required_volume_m3": required_volume,
            "duration_minutes": duration_min,
            "flow_validation_status": data.flow_validation_status,
            "recent_irrigation_credit_status": data.recent_irrigation_credit_status,
            "scientific_tools": [result.model_dump(mode="python") for result in tool_results],
        }

        return {
            "action": action,
            "decision_status": decision_status,
            "recommended_action": recommended,
            "net_irrigation_depth_mm": round(net_need, 3) if net_need is not None else None,
            "gross_irrigation_depth_mm": round(gross_need, 3) if gross_need is not None else None,
            "estimated_volume_m3": round(required_volume, 3) if required_volume is not None else None,
            "duration_minutes": round(duration_min, 2) if duration_min is not None else None,
            "timing_window": data.operating_window if operating_ready else None,
            "confidence": confidence,
            "confidence_score": completeness,
            "evidence_completeness": f"{completeness}%",
            "key_drivers": key_drivers,
            "assumptions": [],
            "limitations": list(dict.fromkeys(limitations)),
            "missing_inputs": unique_missing,
            "verification_requirements": [
                "Preserve the approval record before execution.",
                "Confirm execution from controller, flow-meter, or signed operator evidence.",
                "Compare as-applied volume and runtime with the approved plan.",
                "Record a post-action field or sensor observation before marking the outcome verified.",
            ],
            "calculation_trace": calculation_trace,
            "calibration_status": "explicit_evidence" if operating_ready else "source_review_required",
            "calibration_pack_version": LEGACY_CALIBRATION_PACK_VERSION,
            "recommendation_origin": data.recommendation_origin,
            "duration_basis": (
                "Duration computed by irrigation.duration_from_validated_flow.v1."
                if duration_min is not None
                else "Duration withheld until required volume and validated flow evidence are available."
            ),
            "flow_validation_status": data.flow_validation_status,
            "recent_irrigation_credit_status": data.recent_irrigation_credit_status,
            "validation_warnings": warnings,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

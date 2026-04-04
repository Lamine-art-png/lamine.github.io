"""Irrigation recommendation engine — upgraded to use WaterStateEstimate.

Consumes the shared FeatureSet and WaterStateEstimate so feature logic
is never duplicated. Falls back to direct DB queries when no water state
is available (backward compatibility during rollout).
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.models.block import Block
from app.models.telemetry import Telemetry
from app.schemas.recommendation import IrrigationConstraints, IrrigationTargets
from app.services.feature_builder import FeatureBuilder, FeatureSet
from app.services.water_state_engine import WaterStateEngine, WaterStateEstimate
from app.services.confidence_adjuster import ConfidenceAdjuster

logger = logging.getLogger(__name__)

MODEL_VERSION = "wse-rec-1.1.0"


class Recommender:
    """Water-state-aware irrigation recommender with feedback loop.

    Primary path: FeatureSet → WaterStateEstimate → recommendation.
    Confidence is adjusted by recent verification outcomes (ConfidenceAdjuster).
    """

    def __init__(self):
        self._feature_builder = FeatureBuilder()
        self._engine = WaterStateEngine()
        self._confidence_adjuster = ConfidenceAdjuster()

    def compute(
        self,
        db: Session,
        block_id: str,
        constraints: Optional[IrrigationConstraints],
        targets: Optional[IrrigationTargets],
        horizon_hours: float,
    ) -> Dict:
        """Compute irrigation recommendation.

        Returns:
            {
                "when": datetime,
                "duration_min": float,
                "volume_m3": float,
                "confidence": float,
                "explanations": List[str],
                "version": str,
                "water_state": {...} | None,
            }
        """
        block = db.query(Block).filter(Block.id == block_id).first()
        if not block:
            raise ValueError(f"Block {block_id} not found")

        if not targets:
            targets = IrrigationTargets()

        target_vwc = targets.target_soil_vwc or 0.35
        efficiency = targets.efficiency or 0.85

        # Build features and estimate water state
        fs = self._feature_builder.build(db, block_id)
        estimate = self._engine.estimate(fs)

        # Use water-state-aware deficit calculation
        water_deficit_mm, confidence = self._calculate_deficit_from_state(
            estimate, target_vwc, block.crop_type
        )

        # Blend engine confidence with deficit confidence
        confidence = min(confidence, estimate.confidence)

        # Apply feedback loop: adjust confidence based on verification history
        adjustment = self._confidence_adjuster.compute(db, block_id)
        confidence = max(0.0, min(1.0, confidence * adjustment.multiplier))

        explanations = []
        water_state_summary = {
            "root_zone_vwc": estimate.root_zone_vwc,
            "stress_risk": estimate.stress_risk,
            "refill_status": estimate.refill_status,
            "hours_to_stress": estimate.hours_to_stress,
            "confidence": estimate.confidence,
            "anomaly_flags": estimate.anomaly_flags,
        }
        feedback_summary = {
            "multiplier": adjustment.multiplier,
            "signals": adjustment.adjustment_signals,
            "history_count": adjustment.history_count,
        }

        if water_deficit_mm < 5:
            when = datetime.utcnow() + timedelta(hours=horizon_hours * 0.8)
            duration_min = 0.0
            volume_m3 = 0.0
            explanations.append(
                f"Soil moisture adequate (root-zone VWC: {estimate.root_zone_vwc:.3f}, "
                f"deficit: {water_deficit_mm:.1f}mm)"
            )
            if estimate.refill_status == "refilling":
                explanations.append("Soil is currently refilling — no action needed")
        else:
            when = self._optimal_timing(constraints)

            # Convert mm to m3 based on area
            volume_m3 = (water_deficit_mm / 1000.0) * block.area_ha * 10000 / efficiency

            # Estimate duration (assumes flow rate ~50 m3/hr per ha)
            flow_rate_m3_hr = 50 * block.area_ha
            duration_min = (volume_m3 / flow_rate_m3_hr) * 60

            if constraints:
                if constraints.min_duration_min:
                    duration_min = max(duration_min, constraints.min_duration_min)
                if constraints.max_duration_min:
                    duration_min = min(duration_min, constraints.max_duration_min)

            explanations.append(f"Water deficit: {water_deficit_mm:.1f}mm")
            explanations.append(f"Root-zone VWC: {estimate.root_zone_vwc:.3f}")
            explanations.append(f"Stress risk: {estimate.stress_risk:.2f}")
            explanations.append(f"Refill status: {estimate.refill_status}")
            if estimate.hours_to_stress is not None:
                explanations.append(f"Hours to stress: {estimate.hours_to_stress:.0f}h")
            if estimate.et_demand_mm_day:
                explanations.append(f"ET demand: {estimate.et_demand_mm_day:.1f}mm/day")
            explanations.append(f"Application efficiency: {efficiency * 100:.0f}%")

            # Urgency adjustment
            if estimate.stress_risk > 0.7:
                explanations.append("HIGH STRESS RISK — urgent irrigation recommended")
            elif estimate.hours_to_stress and estimate.hours_to_stress < 24:
                explanations.append(
                    f"APPROACHING STRESS — {estimate.hours_to_stress:.0f}h remaining"
                )

        # Surface feedback signals in explanations
        if "confidence_severely_reduced" in adjustment.adjustment_signals:
            explanations.append(
                f"CONFIDENCE REDUCED — recent verification history poor "
                f"(multiplier: {adjustment.multiplier:.2f})"
            )
        elif "confidence_reduced" in adjustment.adjustment_signals:
            explanations.append(
                f"Confidence adjusted down based on recent outcomes "
                f"(multiplier: {adjustment.multiplier:.2f})"
            )
        for sig in adjustment.adjustment_signals:
            if sig.startswith("repeated_ineffective"):
                explanations.append(
                    f"Warning: {sig} — consider adjusting volume or timing"
                )

        return {
            "when": when,
            "duration_min": round(duration_min, 2),
            "volume_m3": round(volume_m3, 2),
            "confidence": round(confidence, 3),
            "explanations": explanations,
            "version": MODEL_VERSION,
            "water_state": water_state_summary,
            "feedback": feedback_summary,
        }

    def _calculate_deficit_from_state(
        self,
        estimate: WaterStateEstimate,
        target_vwc: float,
        crop_type: Optional[str],
    ) -> Tuple[float, float]:
        """Calculate water deficit using WaterStateEstimate.

        Returns: (deficit_mm, confidence)
        """
        current_vwc = estimate.root_zone_vwc
        et_demand = estimate.et_demand_mm_day or 5.0

        # VWC deficit
        vwc_deficit = target_vwc - current_vwc

        # Root zone depth (mm) by crop
        root_zone_depth = 600
        if crop_type:
            crop_depths = {
                "corn": 800,
                "wheat": 600,
                "vegetables": 400,
                "trees": 1000,
            }
            root_zone_depth = crop_depths.get(crop_type.lower(), 600)

        # Convert VWC deficit to mm
        deficit_from_vwc = vwc_deficit * root_zone_depth

        # ET-based forward projection (3-day)
        et_deficit = et_demand * 3

        # Combine: weight VWC more when we have good data
        if estimate.confidence > 0.6:
            total_deficit = deficit_from_vwc * 0.7 + et_deficit * 0.3
        else:
            total_deficit = deficit_from_vwc * 0.5 + et_deficit * 0.5

        return max(0, total_deficit), estimate.confidence

    def _optimal_timing(
        self, constraints: Optional[IrrigationConstraints]
    ) -> datetime:
        """Determine optimal irrigation timing."""
        now = datetime.utcnow()
        tomorrow_6am = (now + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )

        if not constraints or not constraints.preferred_time_start:
            return tomorrow_6am

        try:
            start_hour, start_min = map(
                int, constraints.preferred_time_start.split(":")
            )
            preferred = now.replace(
                hour=start_hour, minute=start_min, second=0, microsecond=0
            )
            if preferred < now:
                preferred += timedelta(days=1)
            return preferred
        except Exception:
            return tomorrow_6am

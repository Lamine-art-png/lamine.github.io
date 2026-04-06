"""Irrigation recommendation engine — forecast-driven with crop profiles.

Consumes the shared FeatureSet, WaterStateEstimate, and VWCForecast
so feature logic is never duplicated. Uses CropSoilProfile for
per-crop/per-soil thresholds instead of hardcoded constants.
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
from app.services.crop_soil_profile import CropSoilProfile, get_profile
from app.services.forecast_engine import ForecastEngine, VWCForecast

logger = logging.getLogger(__name__)

MODEL_VERSION = "wse-rec-2.0.0"


class Recommender:
    """Forecast-driven irrigation recommender with crop profiles.

    Primary path: FeatureSet → WaterStateEstimate + VWCForecast → recommendation.
    Uses CropSoilProfile for per-crop/per-soil thresholds.
    Confidence is adjusted by recent verification outcomes (ConfidenceAdjuster).
    """

    def __init__(self):
        self._feature_builder = FeatureBuilder()
        self._engine = WaterStateEngine()
        self._forecast_engine = ForecastEngine()
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

        efficiency = targets.efficiency or 0.85

        # Resolve crop/soil profile
        profile = get_profile(block.crop_type, block.soil_type)
        target_vwc = targets.target_soil_vwc or (profile.field_capacity * 0.9)

        # Build features and estimate water state
        fs = self._feature_builder.build(db, block_id)
        estimate = self._engine.estimate(fs)

        # Run forecast for timing intelligence
        forecast = self._forecast_engine.forecast(fs, profile)

        # Use profile-aware deficit calculation
        water_deficit_mm, confidence = self._calculate_deficit_from_state(
            estimate, target_vwc, profile
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
        forecast_summary = {
            "hours_to_stress": forecast.hours_to_stress,
            "optimal_window": forecast.optimal_irrigation_window,
            "confidence": forecast.confidence,
            "profile": forecast.profile_used,
            "points": [
                {"h": p.hours_ahead, "vwc": p.predicted_vwc, "stress": p.stress_risk}
                for p in forecast.points
            ],
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
            # Use forecast-driven timing instead of simple heuristic
            when = self._forecast_optimal_timing(forecast, constraints)

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
            explanations.append(f"Profile: {profile.crop_type}/{profile.soil_type}")
            if forecast.hours_to_stress is not None:
                explanations.append(
                    f"Forecast: stress in {forecast.hours_to_stress:.0f}h"
                )
            if forecast.optimal_irrigation_window:
                explanations.append(
                    f"Optimal window: {forecast.optimal_irrigation_window}"
                )
            if estimate.et_demand_mm_day:
                explanations.append(f"ET demand: {estimate.et_demand_mm_day:.1f}mm/day")
            explanations.append(f"Application efficiency: {efficiency * 100:.0f}%")

            # Urgency from forecast (more precise than water state alone)
            if forecast.hours_to_stress is not None and forecast.hours_to_stress <= 0:
                explanations.append("CRITICAL — crop is already under stress")
            elif forecast.hours_to_stress is not None and forecast.hours_to_stress < 12:
                explanations.append(
                    f"HIGH URGENCY — stress predicted in {forecast.hours_to_stress:.0f}h"
                )
            elif forecast.hours_to_stress is not None and forecast.hours_to_stress < 24:
                explanations.append(
                    f"APPROACHING STRESS — {forecast.hours_to_stress:.0f}h remaining"
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
            "forecast": forecast_summary,
            "feedback": feedback_summary,
        }

    def _calculate_deficit_from_state(
        self,
        estimate: WaterStateEstimate,
        target_vwc: float,
        profile: CropSoilProfile,
    ) -> Tuple[float, float]:
        """Calculate water deficit using WaterStateEstimate and CropSoilProfile.

        Returns: (deficit_mm, confidence)
        """
        current_vwc = estimate.root_zone_vwc
        et_demand = estimate.et_demand_mm_day or 5.0

        # VWC deficit using profile root depth
        vwc_deficit = target_vwc - current_vwc

        # Convert VWC deficit to mm using profile root depth
        deficit_from_vwc = vwc_deficit * profile.root_depth_mm

        # ET-based forward projection (3-day) adjusted by crop coefficient
        et_deficit = et_demand * profile.kc * 3

        # Combine: weight VWC more when we have good data
        if estimate.confidence > 0.6:
            total_deficit = deficit_from_vwc * 0.7 + et_deficit * 0.3
        else:
            total_deficit = deficit_from_vwc * 0.5 + et_deficit * 0.5

        return max(0, total_deficit), estimate.confidence

    def _forecast_optimal_timing(
        self,
        forecast: VWCForecast,
        constraints: Optional[IrrigationConstraints],
    ) -> datetime:
        """Use forecast to determine optimal irrigation timing.

        If forecast says stress is imminent, override preferred time.
        Otherwise respect user constraints.
        """
        now = datetime.utcnow()

        # If stress is imminent (< 12h), irrigate ASAP
        if forecast.hours_to_stress is not None and forecast.hours_to_stress < 12:
            # Respect preferred time only if it's within the stress window
            if constraints and constraints.preferred_time_start:
                try:
                    start_hour, start_min = map(
                        int, constraints.preferred_time_start.split(":")
                    )
                    preferred = now.replace(
                        hour=start_hour, minute=start_min, second=0, microsecond=0
                    )
                    if preferred < now:
                        preferred += timedelta(days=1)
                    hours_until_preferred = (preferred - now).total_seconds() / 3600
                    if hours_until_preferred < forecast.hours_to_stress:
                        return preferred
                except Exception:
                    pass
            # Stress too close — irrigate now or within 2h
            return now + timedelta(hours=2)

        # No imminent stress — use preferred time or default to tomorrow 6am
        if constraints and constraints.preferred_time_start:
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
                pass

        tomorrow_6am = (now + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )
        return tomorrow_6am

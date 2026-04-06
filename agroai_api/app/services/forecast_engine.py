"""VWC Forecast Engine — physics-based soil moisture prediction.

Predicts VWC trajectory at 6h/12h/24h/48h/72h horizons using:
- Current root-zone VWC and trend
- ET demand (crop-coefficient adjusted)
- Recent irrigation and expected refill
- Soil water holding characteristics (from CropSoilProfile)

No ML yet — explicit physics-informed model. Fully testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.services.feature_builder import FeatureSet
from app.services.crop_soil_profile import CropSoilProfile, DEFAULT_PROFILE

logger = logging.getLogger(__name__)

FORECAST_VERSION = "fc-1.0.0"
HORIZONS_HOURS = [6, 12, 24, 48, 72]


@dataclass
class VWCForecastPoint:
    """Single forecast point at a specific horizon."""
    hours_ahead: int
    predicted_vwc: float
    stress_risk: float          # 0-1 at that horizon
    below_stress: bool          # True if predicted VWC < stress threshold
    confidence: float


@dataclass
class VWCForecast:
    """Full forecast trajectory for a block."""
    block_id: str
    computed_at: datetime
    current_vwc: float
    points: List[VWCForecastPoint]
    hours_to_stress: Optional[float]   # None if not on track to stress
    optimal_irrigation_window: Optional[str]  # "now" | "within_Xh" | "not_needed"
    confidence: float
    profile_used: str                  # "corn/loam" or "default/default"
    forecast_version: str = FORECAST_VERSION

    def to_dict(self) -> Dict:
        return {
            "block_id": self.block_id,
            "computed_at": self.computed_at.isoformat(),
            "current_vwc": self.current_vwc,
            "points": [
                {
                    "hours_ahead": p.hours_ahead,
                    "predicted_vwc": p.predicted_vwc,
                    "stress_risk": p.stress_risk,
                    "below_stress": p.below_stress,
                    "confidence": p.confidence,
                }
                for p in self.points
            ],
            "hours_to_stress": self.hours_to_stress,
            "optimal_irrigation_window": self.optimal_irrigation_window,
            "confidence": self.confidence,
            "profile_used": self.profile_used,
            "forecast_version": self.forecast_version,
        }


class ForecastEngine:
    """Stateless: FeatureSet + CropSoilProfile → VWCForecast.

    Physics model:
    VWC(t+h) = VWC(t) - ET_loss(h) + irrigation_refill(h) + rainfall(h)

    Where:
    - ET_loss = (ET0 * Kc * h) / (root_depth_mm) — normalized to VWC units
    - irrigation_refill = decaying refill curve if recent irrigation
    - rainfall = fractional effective rainfall
    """

    def forecast(
        self,
        fs: FeatureSet,
        profile: CropSoilProfile = DEFAULT_PROFILE,
    ) -> VWCForecast:
        """Produce VWC forecast trajectory."""
        now = fs.computed_at
        current_vwc = fs.weighted_root_zone_vwc or fs.mean_vwc or 0.0

        # ET depletion rate in VWC units per hour
        et_rate = self._et_depletion_rate(fs, profile)

        # Recent irrigation refill contribution
        refill_curve = self._irrigation_refill_curve(fs, profile)

        # Compute forecast at each horizon
        points: List[VWCForecastPoint] = []
        hours_to_stress: Optional[float] = None
        stress_found = False

        for h in HORIZONS_HOURS:
            predicted = self._predict_vwc_at(
                current_vwc, et_rate, refill_curve, h, profile
            )

            # Clamp to physical bounds
            predicted = max(profile.wilting_point * 0.8, min(profile.saturation, predicted))

            # Stress risk at this horizon
            vwc_range = profile.field_capacity - profile.wilting_point
            if vwc_range > 0:
                stress_risk = max(0.0, min(1.0,
                    (profile.field_capacity - predicted) / vwc_range
                ))
            else:
                stress_risk = 0.5

            below_stress = predicted < profile.stress_threshold

            # Track first stress crossing
            if below_stress and not stress_found:
                # Interpolate: find exact hour where VWC crosses stress threshold
                hours_to_stress = self._interpolate_stress_crossing(
                    current_vwc, et_rate, refill_curve, profile
                )
                stress_found = True

            # Confidence degrades with horizon
            point_confidence = self._horizon_confidence(fs, h)

            points.append(VWCForecastPoint(
                hours_ahead=h,
                predicted_vwc=round(predicted, 4),
                stress_risk=round(stress_risk, 3),
                below_stress=below_stress,
                confidence=round(point_confidence, 3),
            ))

        # Overall confidence
        overall_confidence = self._overall_confidence(fs, points)

        # Irrigation window recommendation
        window = self._irrigation_window(hours_to_stress, current_vwc, profile)

        return VWCForecast(
            block_id=fs.block_id,
            computed_at=now,
            current_vwc=round(current_vwc, 4),
            points=points,
            hours_to_stress=round(hours_to_stress, 1) if hours_to_stress is not None else None,
            optimal_irrigation_window=window,
            confidence=round(overall_confidence, 3),
            profile_used=f"{profile.crop_type}/{profile.soil_type}",
        )

    # ------------------------------------------------------------------
    # Physics model components
    # ------------------------------------------------------------------

    def _et_depletion_rate(self, fs: FeatureSet, profile: CropSoilProfile) -> float:
        """ET-driven depletion rate in VWC units per hour.

        ET0 (mm/day) * Kc → crop ET (mm/day) → convert to VWC/hour
        VWC change = ET_mm / root_depth_mm
        """
        et0 = fs.et_demand_mm_day or 5.0  # Default 5mm/day if unknown
        crop_et = et0 * profile.kc
        # Convert mm/day to VWC/hour
        vwc_per_hour = (crop_et / profile.root_depth_mm) / 24.0
        return vwc_per_hour

    def _irrigation_refill_curve(
        self, fs: FeatureSet, profile: CropSoilProfile
    ) -> Dict[str, float]:
        """Model post-irrigation refill as exponential decay.

        Returns curve parameters: {peak_hours, refill_vwc, decay_rate}
        """
        if not fs.last_irrigation_at:
            return {"active": False}

        hours_since = (fs.computed_at - fs.last_irrigation_at).total_seconds() / 3600.0

        if hours_since > 72:
            return {"active": False}  # Refill effect has dissipated

        # Estimate refill magnitude from volume
        if fs.last_irrigation_volume_m3 and fs.last_irrigation_volume_m3 > 0:
            # Very rough: convert m3 to mm over assumed area, then to VWC
            # This is approximate — real value comes from observed soil response
            refill_mm = (fs.last_irrigation_volume_m3 / 10.0) * 1000  # rough
            refill_vwc = refill_mm / profile.root_depth_mm
            refill_vwc = min(refill_vwc, 0.15)  # Cap at reasonable max
        else:
            refill_vwc = 0.05  # Default assumption

        return {
            "active": True,
            "hours_since": hours_since,
            "refill_vwc": refill_vwc,
            "decay_rate": 0.03,  # VWC units per hour decay
        }

    def _predict_vwc_at(
        self,
        current_vwc: float,
        et_rate: float,
        refill: Dict,
        hours: int,
        profile: CropSoilProfile,
    ) -> float:
        """Predict VWC at h hours ahead."""
        # ET loss over h hours
        et_loss = et_rate * hours

        # Irrigation refill contribution (decaying)
        refill_contribution = 0.0
        if refill.get("active"):
            hours_since = refill["hours_since"]
            total_hours = hours_since + hours
            # Refill peaks quickly then decays
            if hours_since < 12:
                # Still in active refill window
                remaining_refill = refill["refill_vwc"] * max(0, 1.0 - hours_since / 24.0)
                future_refill = refill["refill_vwc"] * max(0, 1.0 - total_hours / 24.0)
                refill_contribution = max(0, remaining_refill - future_refill)

        predicted = current_vwc - et_loss + refill_contribution

        return predicted

    def _interpolate_stress_crossing(
        self,
        current_vwc: float,
        et_rate: float,
        refill: Dict,
        profile: CropSoilProfile,
    ) -> Optional[float]:
        """Find the hour at which VWC crosses the stress threshold."""
        if current_vwc <= profile.stress_threshold:
            return 0.0

        if et_rate <= 0:
            return None  # Not depleting

        # Binary search for crossing point (within 0.5h precision)
        lo, hi = 0.0, 720.0
        for _ in range(20):
            mid = (lo + hi) / 2.0
            predicted = self._predict_vwc_at(current_vwc, et_rate, refill, int(mid), profile)
            if predicted <= profile.stress_threshold:
                hi = mid
            else:
                lo = mid

        return round(hi, 1) if hi < 720 else None

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _horizon_confidence(self, fs: FeatureSet, hours: int) -> float:
        """Confidence decreases with forecast horizon."""
        # Base from data quality
        base = 1.0
        if fs.data_age_hours and fs.data_age_hours > 2:
            base *= 0.8
        if fs.readings_count_24h < 10:
            base *= 0.8
        if fs.depth_coverage < 0.6:
            base *= 0.7

        # Horizon decay: ~5% per 12 hours
        horizon_factor = max(0.4, 1.0 - (hours / 12.0) * 0.05)

        return max(0.1, base * horizon_factor)

    def _overall_confidence(
        self, fs: FeatureSet, points: List[VWCForecastPoint]
    ) -> float:
        """Overall forecast confidence — average of point confidences."""
        if not points:
            return 0.0
        return sum(p.confidence for p in points) / len(points)

    # ------------------------------------------------------------------
    # Irrigation window
    # ------------------------------------------------------------------

    def _irrigation_window(
        self,
        hours_to_stress: Optional[float],
        current_vwc: float,
        profile: CropSoilProfile,
    ) -> str:
        """Determine optimal irrigation window from forecast."""
        if current_vwc >= profile.field_capacity:
            return "not_needed"

        if hours_to_stress is None:
            return "not_needed"

        if hours_to_stress <= 0:
            return "now"
        elif hours_to_stress <= 12:
            return f"within_{int(hours_to_stress)}h"
        elif hours_to_stress <= 48:
            return f"within_{int(hours_to_stress)}h"
        else:
            return "not_needed"

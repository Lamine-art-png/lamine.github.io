"""Water state engine — stateless estimator that infers root-zone condition.

Takes a FeatureSet (from FeatureBuilder) and produces a WaterStateEstimate.
No database queries — pure computation. The caller is responsible for
persisting the result to the water_states table.

Provider-agnostic: works with any data source that feeds FeatureBuilder.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from app.services.feature_builder import FeatureSet

logger = logging.getLogger(__name__)

ENGINE_VERSION = "wse-1.0.0"

# Agronomic thresholds (provider-agnostic defaults)
# These will move to per-crop / per-soil config in Phase 3.
STRESS_VWC_THRESHOLD = 0.18      # Below this = high stress
FIELD_CAPACITY_VWC = 0.38        # Above this = saturated / refilling
WILTING_POINT_VWC = 0.12         # Permanent wilting point
SATURATION_VWC = 0.45            # Full saturation

# Refill status thresholds (VWC trend % per hour)
DEPLETING_TREND = -0.001         # drying
REFILLING_TREND = 0.001          # wetting
STABLE_BAND = 0.001              # absolute band around zero = stable


@dataclass
class WaterStateEstimate:
    """Output of a single estimation cycle for one block."""
    block_id: str
    estimated_at: datetime

    root_zone_vwc: float
    depth_profile: list          # [{depth_inches, vwc, timestamp}, ...]
    stress_risk: float           # 0 = no stress, 1 = critical
    refill_status: str           # depleting | stable | refilling | saturated | unknown
    depletion_rate: Optional[float]  # VWC % per hour (negative = drying)
    hours_to_stress: Optional[float]
    et_demand_mm_day: Optional[float]
    last_irrigation_at: Optional[datetime]
    last_irrigation_volume_m3: Optional[float]
    confidence: float            # 0-1
    anomaly_flags: List[str]
    feature_snapshot: dict
    engine_version: str = ENGINE_VERSION


class WaterStateEngine:
    """Stateless estimator: FeatureSet → WaterStateEstimate.

    All thresholds are explicit class-level constants.
    No database access, no side effects, fully testable.
    """

    def estimate(self, fs: FeatureSet) -> WaterStateEstimate:
        """Produce a water state estimate from a feature set."""
        root_vwc = fs.weighted_root_zone_vwc or fs.mean_vwc or 0.0
        trend = fs.vwc_trend_pct_per_hour

        stress_risk = self._compute_stress_risk(root_vwc, trend, fs)
        refill_status = self._compute_refill_status(root_vwc, trend)
        hours_to_stress = self._compute_hours_to_stress(root_vwc, trend)
        confidence = self._compute_confidence(fs)

        depth_profile = [
            {
                "depth_inches": d.depth_inches,
                "vwc": d.vwc,
                "timestamp": d.timestamp.isoformat(),
            }
            for d in fs.depth_readings
        ]

        return WaterStateEstimate(
            block_id=fs.block_id,
            estimated_at=fs.computed_at,
            root_zone_vwc=round(root_vwc, 4),
            depth_profile=depth_profile,
            stress_risk=round(stress_risk, 3),
            refill_status=refill_status,
            depletion_rate=round(trend, 6) if trend is not None else None,
            hours_to_stress=round(hours_to_stress, 1) if hours_to_stress is not None else None,
            et_demand_mm_day=round(fs.et_demand_mm_day, 2) if fs.et_demand_mm_day else None,
            last_irrigation_at=fs.last_irrigation_at,
            last_irrigation_volume_m3=fs.last_irrigation_volume_m3,
            confidence=round(confidence, 3),
            anomaly_flags=list(fs.anomalies),
            feature_snapshot=fs.to_dict(),
        )

    # ------------------------------------------------------------------
    # Stress risk (0-1)
    # ------------------------------------------------------------------

    def _compute_stress_risk(
        self, vwc: float, trend: Optional[float], fs: FeatureSet
    ) -> float:
        """Compute stress risk from VWC level, trend, and ET demand.

        Components:
        - Level risk: how close VWC is to wilting point
        - Trend risk: how fast VWC is dropping
        - ET risk: high ET demand amplifies stress when VWC is moderate
        - Data risk: low confidence raises stress conservatively
        """
        # Level risk: linear scale from field capacity (0) to wilting point (1)
        vwc_range = FIELD_CAPACITY_VWC - WILTING_POINT_VWC
        if vwc_range > 0:
            level_risk = max(0.0, min(1.0, (FIELD_CAPACITY_VWC - vwc) / vwc_range))
        else:
            level_risk = 0.5

        # Trend risk: rapid drying increases risk
        trend_risk = 0.0
        if trend is not None and trend < DEPLETING_TREND:
            # Normalize: -0.01 %/hr is moderate, -0.05 is severe
            trend_risk = min(1.0, abs(trend) / 0.05)

        # ET amplifier: high ET on moderate VWC
        et_risk = 0.0
        if fs.et_demand_mm_day and fs.et_demand_mm_day > 5:
            et_factor = min(1.0, (fs.et_demand_mm_day - 5) / 10.0)
            et_risk = et_factor * level_risk * 0.3  # ET amplifies level risk

        # Combine: level dominates
        raw = level_risk * 0.60 + trend_risk * 0.25 + et_risk * 0.15

        # Clamp
        return max(0.0, min(1.0, raw))

    # ------------------------------------------------------------------
    # Refill status
    # ------------------------------------------------------------------

    def _compute_refill_status(
        self, vwc: float, trend: Optional[float]
    ) -> str:
        """Classify current moisture trajectory."""
        if vwc >= SATURATION_VWC:
            return "saturated"

        if trend is None:
            return "unknown"

        if trend < -STABLE_BAND:
            return "depleting"
        elif trend > STABLE_BAND:
            return "refilling"
        else:
            return "stable"

    # ------------------------------------------------------------------
    # Hours to stress
    # ------------------------------------------------------------------

    def _compute_hours_to_stress(
        self, vwc: float, trend: Optional[float]
    ) -> Optional[float]:
        """Estimate hours until VWC reaches stress threshold.

        Only meaningful when trend is negative (depleting).
        Returns None if not depleting or if already stressed.
        """
        if vwc <= STRESS_VWC_THRESHOLD:
            return 0.0  # Already stressed

        if trend is None or trend >= 0:
            return None  # Not depleting

        # trend is negative VWC per hour
        deficit = vwc - STRESS_VWC_THRESHOLD
        hours = deficit / abs(trend)

        # Cap at reasonable maximum
        return min(hours, 720.0)  # 30 days max

    # ------------------------------------------------------------------
    # Confidence score
    # ------------------------------------------------------------------

    def _compute_confidence(self, fs: FeatureSet) -> float:
        """Compute confidence based on data quality indicators.

        Factors:
        - Depth coverage (0-1): more depths = higher confidence
        - Data freshness: stale data reduces confidence
        - Reading count: more readings = better trend estimate
        - Anomalies: each anomaly reduces confidence
        """
        score = 1.0

        # Depth coverage: full coverage = no penalty
        score *= max(0.3, fs.depth_coverage)

        # Data freshness
        if fs.data_age_hours is not None:
            if fs.data_age_hours > 6:
                score *= 0.5
            elif fs.data_age_hours > 2:
                score *= 0.8

        # Reading count in 24h
        if fs.readings_count_24h < 4:
            score *= 0.6
        elif fs.readings_count_24h < 10:
            score *= 0.8

        # Anomaly penalty
        anomaly_penalty = len(fs.anomalies) * 0.1
        score *= max(0.3, 1.0 - anomaly_penalty)

        return max(0.0, min(1.0, score))

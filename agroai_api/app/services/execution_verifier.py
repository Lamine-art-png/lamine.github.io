"""Execution verifier — stateless comparator for planned vs actual irrigation.

Takes planned values, actual execution data, and post-irrigation soil
response. Produces a VerificationResult with outcome classification,
deviation reasons, and effectiveness score.

No database access, no side effects, fully testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

VERIFIER_VERSION = "ev-1.0.0"

# ------------------------------------------------------------------
# Tolerance thresholds
# ------------------------------------------------------------------
DURATION_TOLERANCE_PCT = 15.0    # ±15% duration deviation = acceptable
VOLUME_TOLERANCE_PCT = 20.0      # ±20% volume deviation = acceptable
START_DELAY_TOLERANCE_MIN = 30.0 # 30 min late start = acceptable

# Soil response thresholds
MIN_VWC_RESPONSE = 0.02          # Minimum VWC increase to count as effective
GOOD_VWC_RESPONSE = 0.05         # Strong positive response
VWC_RETENTION_RATIO = 0.5        # At 48h, retain at least 50% of 24h gain


@dataclass
class PlannedExecution:
    """What the recommendation said to do."""
    start: datetime
    duration_min: float
    volume_m3: float


@dataclass
class ActualExecution:
    """What the provider actually did."""
    start: Optional[datetime] = None
    duration_min: Optional[float] = None
    volume_m3: Optional[float] = None
    status: str = "unknown"  # completed | active | cancelled | unknown


@dataclass
class SoilResponse:
    """Observed soil moisture changes after irrigation."""
    pre_vwc: Optional[float] = None
    pre_stress_risk: Optional[float] = None
    post_24h_vwc: Optional[float] = None
    post_48h_vwc: Optional[float] = None
    peak_vwc: Optional[float] = None
    hours_to_peak: Optional[float] = None


@dataclass
class VerificationResult:
    """Output of one verification cycle."""
    outcome: str                     # matched | partially_matched | deviated | failed | agronomically_ineffective
    deviation_reasons: List[str]
    verification_status: str         # pending_24h | pending_48h | complete | insufficient_data

    # Deviations
    duration_deviation_pct: Optional[float] = None
    volume_deviation_pct: Optional[float] = None
    start_delay_minutes: Optional[float] = None

    # Soil deltas
    vwc_delta_24h: Optional[float] = None
    vwc_delta_48h: Optional[float] = None
    peak_vwc: Optional[float] = None
    hours_to_peak: Optional[float] = None

    # Scores
    confidence: float = 0.0
    effectiveness_score: Optional[float] = None

    verifier_version: str = VERIFIER_VERSION


class ExecutionVerifier:
    """Stateless: PlannedExecution + ActualExecution + SoilResponse → VerificationResult.

    All thresholds are explicit class-level constants.
    """

    def verify(
        self,
        planned: PlannedExecution,
        actual: ActualExecution,
        soil: SoilResponse,
    ) -> VerificationResult:
        """Produce a verification result comparing plan vs reality."""
        reasons: List[str] = []

        # ----------------------------------------------------------
        # Step 1: Check if irrigation executed at all
        # ----------------------------------------------------------
        if actual.status == "cancelled":
            return VerificationResult(
                outcome="failed",
                deviation_reasons=["cancelled"],
                verification_status="complete",
                confidence=0.9,
            )

        if actual.status == "unknown" and actual.duration_min is None:
            return VerificationResult(
                outcome="failed",
                deviation_reasons=["no_execution_data"],
                verification_status="insufficient_data",
                confidence=0.3,
            )

        # ----------------------------------------------------------
        # Step 2: Compute execution deviations
        # ----------------------------------------------------------
        dur_dev = self._deviation_pct(planned.duration_min, actual.duration_min)
        vol_dev = self._deviation_pct(planned.volume_m3, actual.volume_m3)
        start_delay = self._start_delay(planned.start, actual.start)

        if dur_dev is not None and abs(dur_dev) > DURATION_TOLERANCE_PCT:
            if dur_dev < 0:
                reasons.append("duration_short")
            else:
                reasons.append("duration_excess")

        if vol_dev is not None and abs(vol_dev) > VOLUME_TOLERANCE_PCT:
            if vol_dev < 0:
                reasons.append("volume_short")
            else:
                reasons.append("volume_excess")

        if start_delay is not None and abs(start_delay) > START_DELAY_TOLERANCE_MIN:
            reasons.append("delayed_start")

        # ----------------------------------------------------------
        # Step 3: Assess soil response
        # ----------------------------------------------------------
        vwc_24h = None
        vwc_48h = None
        effectiveness = None
        v_status = "complete"

        if soil.pre_vwc is not None and soil.post_24h_vwc is not None:
            vwc_24h = soil.post_24h_vwc - soil.pre_vwc

            if soil.post_48h_vwc is not None:
                vwc_48h = soil.post_48h_vwc - soil.pre_vwc
                v_status = "complete"
            else:
                v_status = "pending_48h"

            effectiveness = self._compute_effectiveness(
                vwc_24h, vwc_48h, soil.peak_vwc, soil.pre_vwc
            )

            if vwc_24h < MIN_VWC_RESPONSE:
                reasons.append("no_soil_response")
        elif soil.pre_vwc is not None:
            v_status = "pending_24h"
        else:
            v_status = "insufficient_data"

        # ----------------------------------------------------------
        # Step 4: Classify outcome
        # ----------------------------------------------------------
        outcome = self._classify_outcome(reasons, dur_dev, vol_dev, effectiveness)

        # ----------------------------------------------------------
        # Step 5: Compute confidence
        # ----------------------------------------------------------
        confidence = self._compute_confidence(actual, soil, v_status)

        return VerificationResult(
            outcome=outcome,
            deviation_reasons=reasons,
            verification_status=v_status,
            duration_deviation_pct=round(dur_dev, 1) if dur_dev is not None else None,
            volume_deviation_pct=round(vol_dev, 1) if vol_dev is not None else None,
            start_delay_minutes=round(start_delay, 1) if start_delay is not None else None,
            vwc_delta_24h=round(vwc_24h, 4) if vwc_24h is not None else None,
            vwc_delta_48h=round(vwc_48h, 4) if vwc_48h is not None else None,
            peak_vwc=round(soil.peak_vwc, 4) if soil.peak_vwc is not None else None,
            hours_to_peak=round(soil.hours_to_peak, 1) if soil.hours_to_peak is not None else None,
            confidence=round(confidence, 3),
            effectiveness_score=round(effectiveness, 3) if effectiveness is not None else None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _deviation_pct(
        self, planned: float, actual: Optional[float]
    ) -> Optional[float]:
        if actual is None or planned == 0:
            return None
        return ((actual - planned) / planned) * 100.0

    def _start_delay(
        self, planned: datetime, actual: Optional[datetime]
    ) -> Optional[float]:
        if actual is None:
            return None
        return (actual - planned).total_seconds() / 60.0

    def _compute_effectiveness(
        self,
        vwc_24h: float,
        vwc_48h: Optional[float],
        peak_vwc: Optional[float],
        pre_vwc: float,
    ) -> float:
        """Score 0-1 for agronomic effectiveness.

        Components:
        - Did VWC increase meaningfully at 24h?
        - Is the gain retained at 48h?
        - Did we reach a healthy peak?
        """
        score = 0.0

        # 24h response (0-0.5)
        if vwc_24h >= GOOD_VWC_RESPONSE:
            score += 0.5
        elif vwc_24h >= MIN_VWC_RESPONSE:
            score += 0.3
        elif vwc_24h > 0:
            score += 0.1

        # 48h retention (0-0.3)
        if vwc_48h is not None and vwc_24h > 0:
            retention = vwc_48h / vwc_24h if vwc_24h != 0 else 0
            if retention >= VWC_RETENTION_RATIO:
                score += 0.3
            elif retention > 0:
                score += 0.15

        # Peak quality (0-0.2)
        if peak_vwc is not None and pre_vwc is not None:
            peak_gain = peak_vwc - pre_vwc
            if peak_gain >= GOOD_VWC_RESPONSE:
                score += 0.2
            elif peak_gain >= MIN_VWC_RESPONSE:
                score += 0.1

        return min(1.0, score)

    def _classify_outcome(
        self,
        reasons: List[str],
        dur_dev: Optional[float],
        vol_dev: Optional[float],
        effectiveness: Optional[float],
    ) -> str:
        """Classify the outcome based on deviation reasons and effectiveness."""
        # Failed: no execution data or cancelled (handled earlier)
        if "no_execution_data" in reasons:
            return "failed"

        # Agronomically ineffective: irrigation ran but soil didn't respond
        if effectiveness is not None and effectiveness < 0.15 and "no_soil_response" in reasons:
            return "agronomically_ineffective"

        # Check execution deviations
        has_duration_issue = "duration_short" in reasons or "duration_excess" in reasons
        has_volume_issue = "volume_short" in reasons or "volume_excess" in reasons
        has_major_deviation = False

        if dur_dev is not None and abs(dur_dev) > 50:
            has_major_deviation = True
        if vol_dev is not None and abs(vol_dev) > 50:
            has_major_deviation = True

        if has_major_deviation:
            return "deviated"

        if has_duration_issue or has_volume_issue or "delayed_start" in reasons:
            return "partially_matched"

        return "matched"

    def _compute_confidence(
        self,
        actual: ActualExecution,
        soil: SoilResponse,
        v_status: str,
    ) -> float:
        """Confidence in the verification itself."""
        score = 1.0

        # Actual data completeness
        if actual.duration_min is None:
            score *= 0.5
        if actual.volume_m3 is None:
            score *= 0.7

        # Soil data completeness
        if soil.pre_vwc is None:
            score *= 0.5
        if soil.post_24h_vwc is None:
            score *= 0.6
        if soil.post_48h_vwc is None:
            score *= 0.8

        # Verification completeness
        if v_status == "insufficient_data":
            score *= 0.3
        elif v_status == "pending_24h":
            score *= 0.4
        elif v_status == "pending_48h":
            score *= 0.7

        return max(0.0, min(1.0, score))

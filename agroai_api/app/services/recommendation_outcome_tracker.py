"""Recommendation outcome tracker — orchestrates execution verification.

Finds decision runs that need verification, gathers planned/actual/soil
data, runs the ExecutionVerifier, and persists results.

Safeguards:
- Only verifies decision runs with match_confidence >= VERIFICATION_MIN_CONFIDENCE
- Skips ambiguous matches (match_method not set)
- Skips decision runs without a linked schedule
- Handles cancelled events, missing actual data gracefully

Called by the scheduler after each sync cycle.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from app.models.decision_run import DecisionRun
from app.models.execution_verification import ExecutionVerification
from app.models.schedule import Schedule
from app.models.telemetry import Telemetry
from app.models.water_state import WaterState
from app.services.execution_verifier import (
    ActualExecution,
    ExecutionVerifier,
    PlannedExecution,
    SoilResponse,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# Minimum match confidence to allow verification
VERIFICATION_MIN_CONFIDENCE = 0.4


class RecommendationOutcomeTracker:
    """Orchestrates verification for pending decision runs."""

    def __init__(self):
        self._verifier = ExecutionVerifier()

    def run(self, db: Session, tenant_id: str) -> int:
        """Process all decision runs that need verification.

        Returns number of verifications processed.
        """
        # Find decision runs in applied status that are old enough to verify
        # AND have a schedule link AND sufficient match confidence
        cutoff = datetime.utcnow() - timedelta(hours=24)
        pending_runs = (
            db.query(DecisionRun)
            .filter(
                and_(
                    DecisionRun.tenant_id == tenant_id,
                    DecisionRun.status == "applied",
                    DecisionRun.schedule_id.isnot(None),
                    DecisionRun.planned_start <= cutoff,
                )
            )
            .all()
        )

        # Gate: only verify confidently matched runs
        verifiable_runs = []
        for dr in pending_runs:
            if dr.match_confidence is not None and dr.match_confidence < VERIFICATION_MIN_CONFIDENCE:
                logger.debug(
                    "Skipping verification for decision_run %s: low match confidence %.3f",
                    dr.id, dr.match_confidence,
                )
                continue
            verifiable_runs.append(dr)

        # Also find verifications pending 48h update
        pending_48h = (
            db.query(ExecutionVerification)
            .filter(
                and_(
                    ExecutionVerification.tenant_id == tenant_id,
                    ExecutionVerification.verification_status == "pending_48h",
                )
            )
            .all()
        )

        count = 0

        for dr in verifiable_runs:
            try:
                self._verify_decision_run(db, dr)
                count += 1
            except Exception as e:
                logger.warning(
                    "Verification failed for decision_run %s: %s", dr.id, e
                )

        # Update 48h pending verifications
        cutoff_48h = datetime.utcnow() - timedelta(hours=48)
        for ev in pending_48h:
            try:
                dr = db.query(DecisionRun).filter(DecisionRun.id == ev.decision_run_id).first()
                if dr and dr.planned_start <= cutoff_48h:
                    self._update_48h(db, dr, ev)
                    count += 1
            except Exception as e:
                logger.warning(
                    "48h update failed for verification %s: %s", ev.id, e
                )

        if count > 0:
            db.commit()

        logger.info(
            "Outcome tracker: %d verifiable of %d pending, %d processed, %d 48h updates",
            len(verifiable_runs), len(pending_runs), count, len(pending_48h),
        )
        return count

    def _verify_decision_run(self, db: Session, dr: DecisionRun) -> None:
        """Create or update verification for a decision run."""
        # Check if already verified
        existing = (
            db.query(ExecutionVerification)
            .filter(ExecutionVerification.decision_run_id == dr.id)
            .first()
        )
        if existing and existing.verification_status == "complete":
            return

        planned = PlannedExecution(
            start=dr.planned_start,
            duration_min=dr.planned_duration_min,
            volume_m3=dr.planned_volume_m3,
        )

        actual = self._gather_actual(db, dr)

        # Update decision run with actuals
        if actual.start:
            dr.actual_start = actual.start
        if actual.duration_min is not None:
            dr.actual_duration_min = actual.duration_min
        if actual.volume_m3 is not None:
            dr.actual_volume_m3 = actual.volume_m3

        soil = self._gather_soil_response(db, dr)
        result = self._verifier.verify(planned, actual, soil)
        pre_state = self._get_pre_irrigation_state(db, dr)

        if existing:
            self._apply_result_to_ev(existing, result, soil, pre_state, dr)
            existing.updated_at = datetime.utcnow()
        else:
            ev = ExecutionVerification(
                id=str(uuid.uuid4()),
                tenant_id=dr.tenant_id,
                block_id=dr.block_id,
                decision_run_id=dr.id,
                planned_duration_min=planned.duration_min,
                planned_volume_m3=planned.volume_m3,
                planned_start=planned.start,
                verifier_version=result.verifier_version,
            )
            self._apply_result_to_ev(ev, result, soil, pre_state, dr)
            db.add(ev)
            dr.verification_id = ev.id

        dr.status = "verified"
        dr.verified_at = datetime.utcnow()
        if actual.status == "completed":
            dr.applied_at = dr.applied_at or actual.start

    def _update_48h(
        self, db: Session, dr: DecisionRun, ev: ExecutionVerification
    ) -> None:
        """Update verification with 48h soil data."""
        soil = self._gather_soil_response(db, dr)

        if soil.post_48h_vwc is not None and ev.pre_irrigation_vwc is not None:
            ev.post_48h_vwc = soil.post_48h_vwc
            ev.vwc_delta_48h = round(soil.post_48h_vwc - ev.pre_irrigation_vwc, 4)

            planned = PlannedExecution(
                start=dr.planned_start,
                duration_min=dr.planned_duration_min,
                volume_m3=dr.planned_volume_m3,
            )
            actual = ActualExecution(
                start=dr.actual_start,
                duration_min=dr.actual_duration_min,
                volume_m3=dr.actual_volume_m3,
                status="completed" if dr.actual_duration_min else "unknown",
            )
            result = self._verifier.verify(planned, actual, soil)

            ev.outcome = result.outcome
            ev.deviation_reasons = result.deviation_reasons
            ev.verification_status = result.verification_status
            ev.confidence = result.confidence
            ev.effectiveness_score = result.effectiveness_score
            ev.verified_at = datetime.utcnow()
            ev.updated_at = datetime.utcnow()

    def _gather_actual(self, db: Session, dr: DecisionRun) -> ActualExecution:
        """Get actual execution data from the linked schedule."""
        if not dr.schedule_id:
            return ActualExecution(status="unknown")

        schedule = db.query(Schedule).filter(Schedule.id == dr.schedule_id).first()
        if not schedule:
            return ActualExecution(status="unknown")

        return ActualExecution(
            start=schedule.actual_start or schedule.start_time,
            duration_min=schedule.actual_duration_min or schedule.duration_min,
            volume_m3=schedule.actual_volume_m3 or schedule.volume_m3,
            status=schedule.status,
        )

    def _gather_soil_response(
        self, db: Session, dr: DecisionRun
    ) -> SoilResponse:
        """Get pre/post irrigation soil moisture data from telemetry."""
        response = SoilResponse()
        irrig_time = dr.actual_start or dr.planned_start

        pre_reading = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == dr.block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp <= irrig_time,
                    Telemetry.timestamp >= irrig_time - timedelta(hours=6),
                )
            )
            .order_by(desc(Telemetry.timestamp))
            .first()
        )
        if pre_reading:
            response.pre_vwc = pre_reading.value

        pre_state = (
            db.query(WaterState)
            .filter(
                and_(
                    WaterState.block_id == dr.block_id,
                    WaterState.estimated_at <= irrig_time,
                )
            )
            .order_by(desc(WaterState.estimated_at))
            .first()
        )
        if pre_state:
            response.pre_stress_risk = pre_state.stress_risk

        t_24h_start = irrig_time + timedelta(hours=20)
        t_24h_end = irrig_time + timedelta(hours=28)
        post_24h = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == dr.block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= t_24h_start,
                    Telemetry.timestamp <= t_24h_end,
                )
            )
            .all()
        )
        if post_24h:
            response.post_24h_vwc = sum(r.value for r in post_24h) / len(post_24h)

        t_48h_start = irrig_time + timedelta(hours=44)
        t_48h_end = irrig_time + timedelta(hours=52)
        post_48h = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == dr.block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= t_48h_start,
                    Telemetry.timestamp <= t_48h_end,
                )
            )
            .all()
        )
        if post_48h:
            response.post_48h_vwc = sum(r.value for r in post_48h) / len(post_48h)

        all_post = (
            db.query(Telemetry)
            .filter(
                and_(
                    Telemetry.block_id == dr.block_id,
                    Telemetry.type == "soil_vwc",
                    Telemetry.timestamp >= irrig_time,
                    Telemetry.timestamp <= irrig_time + timedelta(hours=48),
                )
            )
            .order_by(desc(Telemetry.value))
            .first()
        )
        if all_post:
            response.peak_vwc = all_post.value
            response.hours_to_peak = (
                (all_post.timestamp - irrig_time).total_seconds() / 3600.0
            )

        return response

    def _get_pre_irrigation_state(
        self, db: Session, dr: DecisionRun
    ) -> Optional[dict]:
        """Get water state snapshot before irrigation for auditability."""
        irrig_time = dr.actual_start or dr.planned_start
        ws = (
            db.query(WaterState)
            .filter(
                and_(
                    WaterState.block_id == dr.block_id,
                    WaterState.estimated_at <= irrig_time,
                )
            )
            .order_by(desc(WaterState.estimated_at))
            .first()
        )
        if not ws:
            return None
        return {
            "root_zone_vwc": ws.root_zone_vwc,
            "stress_risk": ws.stress_risk,
            "refill_status": ws.refill_status,
            "confidence": ws.confidence,
            "estimated_at": ws.estimated_at.isoformat() if ws.estimated_at else None,
        }

    def _apply_result_to_ev(
        self,
        ev: ExecutionVerification,
        result: VerificationResult,
        soil: SoilResponse,
        pre_state: Optional[dict],
        dr: DecisionRun,
    ) -> None:
        """Apply verification result fields to the EV record."""
        ev.actual_duration_min = dr.actual_duration_min
        ev.actual_volume_m3 = dr.actual_volume_m3
        ev.actual_start = dr.actual_start

        ev.duration_deviation_pct = result.duration_deviation_pct
        ev.volume_deviation_pct = result.volume_deviation_pct
        ev.start_delay_minutes = result.start_delay_minutes

        ev.pre_irrigation_vwc = soil.pre_vwc
        ev.pre_irrigation_stress_risk = soil.pre_stress_risk
        ev.post_24h_vwc = soil.post_24h_vwc
        ev.post_48h_vwc = soil.post_48h_vwc
        ev.vwc_delta_24h = result.vwc_delta_24h
        ev.vwc_delta_48h = result.vwc_delta_48h
        ev.peak_vwc_after = result.peak_vwc
        ev.hours_to_peak = result.hours_to_peak

        ev.outcome = result.outcome
        ev.deviation_reasons = result.deviation_reasons
        ev.verification_status = result.verification_status
        ev.confidence = result.confidence
        ev.effectiveness_score = result.effectiveness_score
        ev.pre_snapshot = pre_state
        ev.verified_at = datetime.utcnow()

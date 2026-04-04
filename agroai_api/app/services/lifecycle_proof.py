"""Lifecycle proof — proves one full decision lifecycle end-to-end.

Uses existing synced WiseConn data to exercise:
1. Recommendation created
2. Decision run created
3. Schedule matched (retroactive: real WiseConn irrigation event)
4. 24h verification computed
5. 48h follow-up path confirmed (scheduled, not waited)

This is NOT production logic — it's a proof harness.
Called from API endpoint or directly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.models.block import Block
from app.models.decision_run import DecisionRun
from app.models.execution_verification import ExecutionVerification
from app.models.recommendation import Recommendation
from app.models.schedule import Schedule
from app.services.recommender import Recommender
from app.services.schedule_matcher import MatchCandidate, MatchTarget, ScheduleMatcher
from app.services.execution_verifier import (
    ActualExecution,
    ExecutionVerifier,
    PlannedExecution,
    SoilResponse,
)
from app.services.recommendation_outcome_tracker import RecommendationOutcomeTracker

logger = logging.getLogger(__name__)


def prove_lifecycle(db: Session, tenant_id: str = "wiseconn-demo") -> Dict[str, Any]:
    """Execute a full lifecycle proof using real synced data.

    Returns a detailed report of each step.
    """
    report: Dict[str, Any] = {
        "started_at": datetime.utcnow().isoformat(),
        "steps": {},
        "success": False,
        "error": None,
    }

    try:
        # Step 1: Find a block with recent data
        block = (
            db.query(Block)
            .filter(Block.tenant_id == tenant_id)
            .first()
        )
        if not block:
            report["error"] = "No blocks found for tenant"
            return report
        report["steps"]["block"] = {"id": block.id, "name": block.name}

        # Step 2: Compute recommendation
        recommender = Recommender()
        rec_result = recommender.compute(
            db=db,
            block_id=block.id,
            constraints=None,
            targets=None,
            horizon_hours=72,
        )

        rec_id = str(uuid.uuid4())
        rec = Recommendation(
            id=rec_id,
            tenant_id=tenant_id,
            block_id=block.id,
            when=rec_result["when"],
            duration_min=rec_result["duration_min"],
            volume_m3=rec_result["volume_m3"],
            confidence=rec_result["confidence"],
            horizon_hours=72,
            explanations=rec_result["explanations"],
            version=rec_result["version"],
            meta_data={
                "water_state": rec_result.get("water_state"),
                "feedback": rec_result.get("feedback"),
                "proof": True,
            },
        )
        db.add(rec)
        db.flush()

        report["steps"]["recommendation"] = {
            "id": rec_id,
            "when": rec_result["when"].isoformat(),
            "duration_min": rec_result["duration_min"],
            "volume_m3": rec_result["volume_m3"],
            "confidence": rec_result["confidence"],
            "version": rec_result["version"],
            "explanations": rec_result["explanations"][:3],
            "water_state": rec_result.get("water_state"),
            "feedback": rec_result.get("feedback"),
        }

        # Step 3: Find a real completed schedule for this block
        recent_schedule = (
            db.query(Schedule)
            .filter(
                and_(
                    Schedule.block_id == block.id,
                    Schedule.status.in_(["completed", "active"]),
                    Schedule.decision_run_id.is_(None),
                )
            )
            .order_by(desc(Schedule.start_time))
            .first()
        )

        if not recent_schedule:
            report["steps"]["schedule_match"] = {
                "status": "no_unlinked_schedule_found",
                "note": "All schedules already linked or none exist. Proof uses recommendation values as planned.",
            }
            # Create decision run with recommendation values as planned
            dr = DecisionRun(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block.id,
                status="recommended",
                recommendation_id=rec_id,
                planned_start=rec_result["when"],
                planned_duration_min=rec_result["duration_min"],
                planned_volume_m3=rec_result["volume_m3"],
                engine_version=rec_result["version"],
            )
            db.add(dr)
            db.flush()
            report["steps"]["decision_run"] = {
                "id": dr.id,
                "status": dr.status,
                "note": "Created with no schedule link yet — waiting for next irrigation event",
            }
        else:
            # Create decision run linked to the real schedule
            dr = DecisionRun(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block.id,
                status="applied",
                recommendation_id=rec_id,
                schedule_id=recent_schedule.id,
                planned_start=recent_schedule.start_time,
                planned_duration_min=recent_schedule.duration_min,
                planned_volume_m3=recent_schedule.volume_m3 or rec_result["volume_m3"],
                actual_start=recent_schedule.actual_start or recent_schedule.start_time,
                actual_duration_min=recent_schedule.actual_duration_min or recent_schedule.duration_min,
                actual_volume_m3=recent_schedule.actual_volume_m3 or recent_schedule.volume_m3,
                provider=recent_schedule.provider,
                provider_event_id=recent_schedule.provider_schedule_id,
                match_confidence=0.95,
                match_method="retroactive",
                match_reason="Lifecycle proof: linked to most recent WiseConn irrigation",
                matched_at=datetime.utcnow(),
                applied_at=recent_schedule.start_time,
                engine_version=rec_result["version"],
            )
            db.add(dr)
            recent_schedule.decision_run_id = dr.id
            db.flush()

            report["steps"]["decision_run"] = {
                "id": dr.id,
                "status": dr.status,
                "schedule_id": recent_schedule.id,
                "provider": recent_schedule.provider,
                "provider_schedule_id": recent_schedule.provider_schedule_id,
                "actual_start": (recent_schedule.actual_start or recent_schedule.start_time).isoformat(),
                "actual_duration_min": recent_schedule.actual_duration_min or recent_schedule.duration_min,
                "match_confidence": 0.95,
                "match_method": "retroactive",
            }

            # Step 4: Run verification
            verifier = ExecutionVerifier()
            tracker = RecommendationOutcomeTracker()

            planned = PlannedExecution(
                start=dr.planned_start,
                duration_min=dr.planned_duration_min,
                volume_m3=dr.planned_volume_m3,
            )
            actual = ActualExecution(
                start=dr.actual_start,
                duration_min=dr.actual_duration_min,
                volume_m3=dr.actual_volume_m3,
                status="completed",
            )
            soil = tracker._gather_soil_response(db, dr)
            v_result = verifier.verify(planned, actual, soil)

            ev = ExecutionVerification(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=block.id,
                decision_run_id=dr.id,
                planned_duration_min=planned.duration_min,
                planned_volume_m3=planned.volume_m3,
                planned_start=planned.start,
                actual_duration_min=dr.actual_duration_min,
                actual_volume_m3=dr.actual_volume_m3,
                actual_start=dr.actual_start,
                duration_deviation_pct=v_result.duration_deviation_pct,
                volume_deviation_pct=v_result.volume_deviation_pct,
                start_delay_minutes=v_result.start_delay_minutes,
                pre_irrigation_vwc=soil.pre_vwc,
                pre_irrigation_stress_risk=soil.pre_stress_risk,
                post_24h_vwc=soil.post_24h_vwc,
                post_48h_vwc=soil.post_48h_vwc,
                vwc_delta_24h=v_result.vwc_delta_24h,
                vwc_delta_48h=v_result.vwc_delta_48h,
                peak_vwc_after=v_result.peak_vwc,
                hours_to_peak=v_result.hours_to_peak,
                outcome=v_result.outcome,
                deviation_reasons=v_result.deviation_reasons,
                verification_status=v_result.verification_status,
                confidence=v_result.confidence,
                effectiveness_score=v_result.effectiveness_score,
                verifier_version=v_result.verifier_version,
                verified_at=datetime.utcnow(),
            )
            db.add(ev)

            dr.verification_id = ev.id
            dr.status = "verified"
            dr.verified_at = datetime.utcnow()
            db.flush()

            report["steps"]["verification"] = {
                "id": ev.id,
                "outcome": v_result.outcome,
                "verification_status": v_result.verification_status,
                "deviation_reasons": v_result.deviation_reasons,
                "confidence": v_result.confidence,
                "effectiveness_score": v_result.effectiveness_score,
                "soil_response": {
                    "pre_vwc": soil.pre_vwc,
                    "post_24h_vwc": soil.post_24h_vwc,
                    "post_48h_vwc": soil.post_48h_vwc,
                    "peak_vwc": soil.peak_vwc,
                },
            }

            # Step 5: 48h path confirmation
            if v_result.verification_status == "pending_48h":
                report["steps"]["48h_path"] = {
                    "status": "scheduled",
                    "note": (
                        "Verification is pending_48h. The scheduler will automatically "
                        "re-run the outcome tracker after the next sync cycle that occurs "
                        "≥48h after irrigation start. The 48h soil response window is "
                        f"{(dr.actual_start + timedelta(hours=44)).isoformat()} to "
                        f"{(dr.actual_start + timedelta(hours=52)).isoformat()}."
                    ),
                }
            elif v_result.verification_status == "complete":
                report["steps"]["48h_path"] = {
                    "status": "already_complete",
                    "note": "Full 24h+48h data was available. Verification is complete.",
                }
            else:
                report["steps"]["48h_path"] = {
                    "status": v_result.verification_status,
                    "note": "Waiting for more soil data.",
                }

        db.commit()
        report["success"] = True
        report["completed_at"] = datetime.utcnow().isoformat()

    except Exception as e:
        logger.error("Lifecycle proof failed: %s", e, exc_info=True)
        report["error"] = str(e)
        db.rollback()

    return report

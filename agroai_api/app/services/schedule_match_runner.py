"""Schedule match runner — wires ScheduleMatcher into the sync pipeline.

After each sync, finds:
1. Decision runs without a schedule match (forward matching)
2. Schedules without a decision run link (retroactive matching)

Uses ScheduleMatcher for scoring, then persists links and metadata.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.decision_run import DecisionRun
from app.models.recommendation import Recommendation
from app.models.schedule import Schedule
from app.services.schedule_matcher import (
    MatchCandidate,
    MatchResult,
    MatchTarget,
    ScheduleMatcher,
    MIN_MATCH_CONFIDENCE,
)

logger = logging.getLogger(__name__)


class ScheduleMatchRunner:
    """Orchestrates schedule matching after each sync cycle."""

    def __init__(self):
        self._matcher = ScheduleMatcher()

    def run(self, db: Session, tenant_id: str) -> Dict:
        """Run all matching passes. Returns summary."""
        summary = {
            "forward_matched": 0,
            "retroactive_created": 0,
            "ambiguous_skipped": 0,
            "no_match": 0,
        }

        # Pass 1: Forward — decision runs that need a schedule
        summary["forward_matched"] = self._forward_match(db, tenant_id)

        # Pass 2: Retroactive — completed schedules with no decision run
        retro = self._retroactive_match(db, tenant_id)
        summary["retroactive_created"] = retro["created"]
        summary["ambiguous_skipped"] += retro["ambiguous_skipped"]
        summary["no_match"] += retro["no_match"]

        if summary["forward_matched"] + summary["retroactive_created"] > 0:
            db.commit()

        logger.info(
            "Schedule matching: %d forward, %d retroactive, %d ambiguous, %d unmatched",
            summary["forward_matched"],
            summary["retroactive_created"],
            summary["ambiguous_skipped"],
            summary["no_match"],
        )
        return summary

    def _forward_match(self, db: Session, tenant_id: str) -> int:
        """Match decision runs that have no schedule_id yet."""
        unmatched_runs = (
            db.query(DecisionRun)
            .filter(
                and_(
                    DecisionRun.tenant_id == tenant_id,
                    DecisionRun.schedule_id.is_(None),
                    DecisionRun.status.in_(["recommended", "approved", "scheduled"]),
                )
            )
            .all()
        )

        if not unmatched_runs:
            return 0

        # Get candidate schedules (recent, not yet linked)
        lookback = datetime.utcnow() - timedelta(days=14)
        candidate_schedules = (
            db.query(Schedule)
            .filter(
                and_(
                    Schedule.tenant_id == tenant_id,
                    Schedule.start_time >= lookback,
                    Schedule.decision_run_id.is_(None),
                )
            )
            .all()
        )

        candidates = [self._schedule_to_candidate(s) for s in candidate_schedules]
        schedule_lookup = {s.id: s for s in candidate_schedules}
        matched = 0

        for dr in unmatched_runs:
            target = MatchTarget(
                decision_run_id=dr.id,
                block_id=dr.block_id,
                planned_start=dr.planned_start,
                planned_duration_min=dr.planned_duration_min,
                planned_volume_m3=dr.planned_volume_m3,
                provider_event_id=dr.provider_event_id,
            )
            result = self._matcher.match(target, candidates)

            if result.matched and not result.ambiguous:
                self._apply_match(dr, schedule_lookup[result.schedule_id], result)
                # Remove matched schedule from candidates for subsequent runs
                candidates = [c for c in candidates if c.schedule_id != result.schedule_id]
                matched += 1
            elif result.ambiguous:
                logger.info(
                    "Ambiguous match for decision_run %s: confidence=%.3f, method=%s",
                    dr.id, result.confidence, result.method,
                )

        return matched

    def _retroactive_match(self, db: Session, tenant_id: str) -> Dict:
        """Create decision runs for completed schedules that have no link.

        This handles the common case: irrigation happened via provider,
        AGRO-AI sees it during sync, but no recommendation triggered it.
        We still create a decision run so verification can proceed.
        """
        result = {"created": 0, "ambiguous_skipped": 0, "no_match": 0}

        # Completed schedules with no decision run link, within last 7 days
        lookback = datetime.utcnow() - timedelta(days=7)
        orphan_schedules = (
            db.query(Schedule)
            .filter(
                and_(
                    Schedule.tenant_id == tenant_id,
                    Schedule.decision_run_id.is_(None),
                    Schedule.status.in_(["completed", "active"]),
                    Schedule.start_time >= lookback,
                )
            )
            .all()
        )

        if not orphan_schedules:
            return result

        # Check which already have a decision run pointing to them
        existing_schedule_ids = set()
        existing_drs = (
            db.query(DecisionRun.schedule_id)
            .filter(
                and_(
                    DecisionRun.tenant_id == tenant_id,
                    DecisionRun.schedule_id.isnot(None),
                )
            )
            .all()
        )
        for row in existing_drs:
            if row[0]:
                existing_schedule_ids.add(row[0])

        for sched in orphan_schedules:
            if sched.id in existing_schedule_ids:
                continue

            # Create a retroactive decision run (no recommendation link — observed event)
            dr = DecisionRun(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                block_id=sched.block_id,
                status="applied",
                recommendation_id="retroactive",  # Sentinel: no recommendation triggered this
                schedule_id=sched.id,
                planned_start=sched.start_time,
                planned_duration_min=sched.duration_min,
                planned_volume_m3=sched.volume_m3 or 0.0,
                actual_start=sched.actual_start or sched.start_time,
                actual_duration_min=sched.actual_duration_min or sched.duration_min,
                actual_volume_m3=sched.actual_volume_m3 or sched.volume_m3,
                provider=sched.provider,
                provider_event_id=sched.provider_schedule_id,
                match_confidence=0.95,
                match_method="retroactive",
                match_reason="Provider irrigation event with no prior recommendation",
                matched_at=datetime.utcnow(),
                applied_at=sched.start_time,
            )
            db.add(dr)

            # Link schedule back
            sched.decision_run_id = dr.id

            result["created"] += 1

        return result

    def _schedule_to_candidate(self, s: Schedule) -> MatchCandidate:
        return MatchCandidate(
            schedule_id=s.id,
            block_id=s.block_id,
            start_time=s.start_time,
            duration_min=s.duration_min,
            volume_m3=s.volume_m3,
            status=s.status,
            provider=s.provider,
            provider_schedule_id=s.provider_schedule_id,
        )

    def _apply_match(
        self, dr: DecisionRun, schedule: Schedule, result: MatchResult
    ) -> None:
        """Apply a successful match to both records."""
        dr.schedule_id = schedule.id
        dr.match_confidence = result.confidence
        dr.match_method = result.method
        dr.match_reason = result.reason
        dr.matched_at = datetime.utcnow()
        dr.provider = schedule.provider
        dr.provider_event_id = schedule.provider_schedule_id

        # Pull actual values from schedule
        dr.actual_start = schedule.actual_start or schedule.start_time
        dr.actual_duration_min = schedule.actual_duration_min or schedule.duration_min
        dr.actual_volume_m3 = schedule.actual_volume_m3 or schedule.volume_m3

        # Advance status
        if schedule.status == "completed":
            dr.status = "applied"
            dr.applied_at = datetime.utcnow()
        elif schedule.status == "active":
            dr.status = "scheduled"
            dr.scheduled_at = datetime.utcnow()

        # Link schedule back
        schedule.decision_run_id = dr.id

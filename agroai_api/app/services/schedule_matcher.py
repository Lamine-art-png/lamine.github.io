"""Schedule matcher — links provider irrigation events to DecisionRun records.

Provider-agnostic matching logic. Uses deterministic rules in priority order:
1. Provider event ID match (exact, highest confidence)
2. Same block + overlapping time window
3. Duration proximity
4. Volume proximity (when available)

Supports both forward matching (decision run exists, schedule arrives) and
retroactive matching (schedule exists, decision run created later).

No side effects in the matching logic itself — the caller persists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

MATCHER_VERSION = "sm-1.0.0"

# Matching thresholds
TIME_WINDOW_HOURS = 4.0          # Max hours between planned and actual start
DURATION_MATCH_PCT = 50.0        # Duration within 50% = plausible match
VOLUME_MATCH_PCT = 50.0          # Volume within 50% = plausible match
MIN_MATCH_CONFIDENCE = 0.3       # Below this, don't match at all
AMBIGUOUS_CONFIDENCE_GAP = 0.15  # If two candidates are within this gap, flag ambiguous


@dataclass
class MatchCandidate:
    """A schedule that could correspond to a decision run."""
    schedule_id: str
    block_id: str
    start_time: datetime
    duration_min: float
    volume_m3: Optional[float]
    status: str
    provider: Optional[str]
    provider_schedule_id: Optional[str]


@dataclass
class MatchTarget:
    """A decision run seeking a schedule match."""
    decision_run_id: str
    block_id: str
    planned_start: datetime
    planned_duration_min: float
    planned_volume_m3: float
    provider_event_id: Optional[str]


@dataclass
class MatchResult:
    """Output of one matching attempt."""
    matched: bool
    schedule_id: Optional[str] = None
    confidence: float = 0.0
    method: str = "none"           # provider_id | time_block | time_duration | retroactive
    reason: str = ""
    ambiguous: bool = False        # True if multiple candidates scored close


class ScheduleMatcher:
    """Stateless: MatchTarget + List[MatchCandidate] → MatchResult.

    All thresholds are explicit class-level constants.
    """

    def match(
        self,
        target: MatchTarget,
        candidates: List[MatchCandidate],
    ) -> MatchResult:
        """Find the best schedule match for a decision run."""
        if not candidates:
            return MatchResult(matched=False, reason="no_candidates")

        # Filter to same block only
        block_candidates = [c for c in candidates if c.block_id == target.block_id]
        if not block_candidates:
            return MatchResult(matched=False, reason="no_candidates_for_block")

        # Filter out cancelled schedules
        active_candidates = [c for c in block_candidates if c.status != "cancelled"]
        if not active_candidates:
            return MatchResult(matched=False, reason="all_candidates_cancelled")

        scored: List[Tuple[float, str, str, MatchCandidate]] = []

        for cand in active_candidates:
            conf, method, reason = self._score_candidate(target, cand)
            if conf >= MIN_MATCH_CONFIDENCE:
                scored.append((conf, method, reason, cand))

        if not scored:
            return MatchResult(matched=False, reason="no_candidate_above_threshold")

        # Sort by confidence descending
        scored.sort(key=lambda x: x[0], reverse=True)

        best_conf, best_method, best_reason, best_cand = scored[0]

        # Check for ambiguity
        ambiguous = False
        if len(scored) > 1:
            second_conf = scored[1][0]
            if best_conf - second_conf < AMBIGUOUS_CONFIDENCE_GAP:
                ambiguous = True

        return MatchResult(
            matched=True,
            schedule_id=best_cand.schedule_id,
            confidence=round(best_conf, 3),
            method=best_method,
            reason=best_reason,
            ambiguous=ambiguous,
        )

    def _score_candidate(
        self, target: MatchTarget, cand: MatchCandidate
    ) -> Tuple[float, str, str]:
        """Score a single candidate. Returns (confidence, method, reason)."""

        # Priority 1: Exact provider event ID match
        if (
            target.provider_event_id
            and cand.provider_schedule_id
            and str(target.provider_event_id) == str(cand.provider_schedule_id)
        ):
            return (0.99, "provider_id", f"Exact provider ID match: {cand.provider_schedule_id}")

        # Priority 2+: Time-based matching
        time_delta = self._time_delta_hours(target.planned_start, cand.start_time)
        if time_delta > TIME_WINDOW_HOURS:
            return (0.0, "none", f"Time gap too large: {time_delta:.1f}h")

        # Time proximity score (0-0.5): closer = higher
        time_score = max(0, 0.5 * (1.0 - time_delta / TIME_WINDOW_HOURS))

        # Duration proximity score (0-0.3)
        dur_dev = self._deviation_pct(target.planned_duration_min, cand.duration_min)
        if dur_dev is not None and abs(dur_dev) <= DURATION_MATCH_PCT:
            dur_score = 0.3 * (1.0 - abs(dur_dev) / DURATION_MATCH_PCT)
        else:
            dur_score = 0.0

        # Volume proximity score (0-0.2)
        vol_score = 0.0
        if target.planned_volume_m3 > 0 and cand.volume_m3 and cand.volume_m3 > 0:
            vol_dev = self._deviation_pct(target.planned_volume_m3, cand.volume_m3)
            if vol_dev is not None and abs(vol_dev) <= VOLUME_MATCH_PCT:
                vol_score = 0.2 * (1.0 - abs(vol_dev) / VOLUME_MATCH_PCT)

        total = time_score + dur_score + vol_score

        # Determine method
        if dur_score > 0:
            method = "time_duration"
            reason = f"Time delta: {time_delta:.1f}h, duration dev: {dur_dev:.0f}%"
        else:
            method = "time_block"
            reason = f"Time delta: {time_delta:.1f}h, same block"

        return (total, method, reason)

    def _time_delta_hours(self, a: datetime, b: datetime) -> float:
        return abs((a - b).total_seconds()) / 3600.0

    def _deviation_pct(self, planned: float, actual: float) -> Optional[float]:
        if planned == 0:
            return None
        return ((actual - planned) / planned) * 100.0

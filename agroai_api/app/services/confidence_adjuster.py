"""Confidence adjuster — feedback loop from verification outcomes to recommender.

Computes a per-block confidence adjustment based on recent verification history.
Uses explicit, auditable rules. No opaque ML.

Rules:
- Recent matched outcomes → allow confidence to rise (within safe bounds)
- Recent agronomically_ineffective outcomes → reduce confidence, surface signal
- Recent deviated or failed outcomes → reduce confidence
- Insufficient history → return neutral (no adjustment)

The adjustment is a multiplier (0.5 - 1.2) applied to the recommender's
base confidence. The evidence used is persisted for auditability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.models.execution_verification import ExecutionVerification

logger = logging.getLogger(__name__)

# Minimum verifications needed before adjusting
MIN_HISTORY = 3

# Lookback window for recent verifications
LOOKBACK_DAYS = 30

# Outcome weights for the adjustment score
# Positive = good for confidence, negative = bad
OUTCOME_WEIGHTS: Dict[str, float] = {
    "matched": 0.2,
    "partially_matched": 0.05,
    "deviated": -0.15,
    "failed": -0.25,
    "agronomically_ineffective": -0.3,
}

# Bounds on the multiplier
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 1.2
NEUTRAL_MULTIPLIER = 1.0


@dataclass
class ConfidenceAdjustment:
    """Output of confidence adjustment for one block."""
    block_id: str
    multiplier: float               # 0.5 - 1.2
    adjustment_signals: List[str]    # Human-readable signals
    evidence: Dict                   # Counts and scores used
    history_count: int
    computed_at: datetime = field(default_factory=datetime.utcnow)


class ConfidenceAdjuster:
    """Stateless: block verification history → ConfidenceAdjustment.

    Query the DB for recent verifications, compute adjustment.
    """

    def compute(
        self, db: Session, block_id: str
    ) -> ConfidenceAdjustment:
        """Compute confidence adjustment for a block."""
        lookback = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)

        verifications = (
            db.query(ExecutionVerification)
            .filter(
                and_(
                    ExecutionVerification.block_id == block_id,
                    ExecutionVerification.verification_status == "complete",
                    ExecutionVerification.verified_at >= lookback,
                )
            )
            .order_by(desc(ExecutionVerification.verified_at))
            .limit(20)
            .all()
        )

        history_count = len(verifications)

        if history_count < MIN_HISTORY:
            return ConfidenceAdjustment(
                block_id=block_id,
                multiplier=NEUTRAL_MULTIPLIER,
                adjustment_signals=["insufficient_history"],
                evidence={"count": history_count, "min_required": MIN_HISTORY},
                history_count=history_count,
            )

        # Count outcomes
        outcome_counts: Dict[str, int] = {}
        effectiveness_scores: List[float] = []
        for ev in verifications:
            outcome_counts[ev.outcome] = outcome_counts.get(ev.outcome, 0) + 1
            if ev.effectiveness_score is not None:
                effectiveness_scores.append(ev.effectiveness_score)

        # Compute weighted score
        raw_score = 0.0
        for outcome, count in outcome_counts.items():
            weight = OUTCOME_WEIGHTS.get(outcome, 0.0)
            raw_score += weight * count

        # Normalize by number of verifications
        normalized = raw_score / history_count

        # Convert to multiplier (centered at 1.0)
        multiplier = NEUTRAL_MULTIPLIER + normalized
        multiplier = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier))

        # Build signals
        signals: List[str] = []

        matched_count = outcome_counts.get("matched", 0)
        ineffective_count = outcome_counts.get("agronomically_ineffective", 0)
        failed_count = outcome_counts.get("failed", 0)
        deviated_count = outcome_counts.get("deviated", 0)

        matched_rate = matched_count / history_count
        if matched_rate >= 0.7:
            signals.append(f"high_match_rate:{matched_rate:.0%}")
        elif matched_rate < 0.3:
            signals.append(f"low_match_rate:{matched_rate:.0%}")

        if ineffective_count >= 2:
            signals.append(f"repeated_ineffective:{ineffective_count}")

        if failed_count >= 2:
            signals.append(f"repeated_failures:{failed_count}")

        if deviated_count >= 2:
            signals.append(f"repeated_deviations:{deviated_count}")

        avg_effectiveness = None
        if effectiveness_scores:
            avg_effectiveness = sum(effectiveness_scores) / len(effectiveness_scores)
            if avg_effectiveness < 0.3:
                signals.append(f"low_avg_effectiveness:{avg_effectiveness:.2f}")
            elif avg_effectiveness > 0.7:
                signals.append(f"high_avg_effectiveness:{avg_effectiveness:.2f}")

        if multiplier < 0.7:
            signals.append("confidence_severely_reduced")
        elif multiplier < 0.9:
            signals.append("confidence_reduced")
        elif multiplier > 1.1:
            signals.append("confidence_boosted")

        return ConfidenceAdjustment(
            block_id=block_id,
            multiplier=round(multiplier, 3),
            adjustment_signals=signals,
            evidence={
                "outcome_counts": outcome_counts,
                "avg_effectiveness": round(avg_effectiveness, 3) if avg_effectiveness is not None else None,
                "raw_score": round(raw_score, 3),
                "normalized_score": round(normalized, 3),
                "lookback_days": LOOKBACK_DAYS,
            },
            history_count=history_count,
        )

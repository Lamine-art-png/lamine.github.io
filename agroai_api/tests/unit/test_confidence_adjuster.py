"""Unit tests for ConfidenceAdjuster — uses test DB."""
import pytest
import uuid
from datetime import datetime, timedelta

from app.models.execution_verification import ExecutionVerification
from app.services.confidence_adjuster import (
    ConfidenceAdjuster,
    MIN_HISTORY,
    NEUTRAL_MULTIPLIER,
    MIN_MULTIPLIER,
    MAX_MULTIPLIER,
)


def _add_verification(
    db,
    block_id: str,
    tenant_id: str,
    outcome: str,
    effectiveness: float = None,
    days_ago: int = 1,
):
    """Helper to add a completed verification to the test DB."""
    ev = ExecutionVerification(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        block_id=block_id,
        decision_run_id=str(uuid.uuid4()),
        planned_duration_min=60,
        planned_volume_m3=50,
        planned_start=datetime.utcnow() - timedelta(days=days_ago + 1),
        outcome=outcome,
        deviation_reasons=[],
        verification_status="complete",
        confidence=0.8,
        effectiveness_score=effectiveness,
        verifier_version="ev-1.0.0",
        verified_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(ev)
    db.commit()
    return ev


@pytest.fixture
def adjuster():
    return ConfidenceAdjuster()


class TestInsufficientHistory:
    def test_returns_neutral_with_no_history(self, adjuster, db, test_block):
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier == NEUTRAL_MULTIPLIER
        assert "insufficient_history" in result.adjustment_signals
        assert result.history_count == 0

    def test_returns_neutral_with_few_verifications(self, adjuster, db, test_block):
        _add_verification(db, test_block.id, test_block.tenant_id, "matched")
        _add_verification(db, test_block.id, test_block.tenant_id, "matched")
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier == NEUTRAL_MULTIPLIER
        assert result.history_count == 2


class TestPositiveHistory:
    def test_all_matched_boosts_confidence(self, adjuster, db, test_block):
        for i in range(5):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "matched", effectiveness=0.8, days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier > NEUTRAL_MULTIPLIER
        assert result.multiplier <= MAX_MULTIPLIER
        assert "high_match_rate" in " ".join(result.adjustment_signals)

    def test_mostly_matched_still_above_neutral(self, adjuster, db, test_block):
        for i in range(4):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "matched", effectiveness=0.7, days_ago=i + 1,
            )
        _add_verification(
            db, test_block.id, test_block.tenant_id,
            "partially_matched", effectiveness=0.5, days_ago=5,
        )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier >= NEUTRAL_MULTIPLIER


class TestNegativeHistory:
    def test_repeated_ineffective_reduces_confidence(self, adjuster, db, test_block):
        for i in range(4):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "agronomically_ineffective", effectiveness=0.1, days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier < NEUTRAL_MULTIPLIER
        assert any("repeated_ineffective" in s for s in result.adjustment_signals)

    def test_repeated_failures_reduces_confidence(self, adjuster, db, test_block):
        for i in range(4):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "failed", effectiveness=None, days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier < 0.8

    def test_mixed_bad_outcomes_reduces(self, adjuster, db, test_block):
        _add_verification(db, test_block.id, test_block.tenant_id, "failed", days_ago=1)
        _add_verification(db, test_block.id, test_block.tenant_id, "deviated", days_ago=2)
        _add_verification(db, test_block.id, test_block.tenant_id, "agronomically_ineffective", effectiveness=0.1, days_ago=3)
        _add_verification(db, test_block.id, test_block.tenant_id, "matched", effectiveness=0.8, days_ago=4)
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier < NEUTRAL_MULTIPLIER


class TestBounds:
    def test_multiplier_never_below_minimum(self, adjuster, db, test_block):
        for i in range(10):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "failed", days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier >= MIN_MULTIPLIER

    def test_multiplier_never_above_maximum(self, adjuster, db, test_block):
        for i in range(10):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "matched", effectiveness=0.95, days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert result.multiplier <= MAX_MULTIPLIER


class TestEvidence:
    def test_evidence_includes_counts(self, adjuster, db, test_block):
        for i in range(3):
            _add_verification(db, test_block.id, test_block.tenant_id, "matched", effectiveness=0.7, days_ago=i + 1)
        _add_verification(db, test_block.id, test_block.tenant_id, "deviated", days_ago=4)
        result = adjuster.compute(db, test_block.id)
        assert "outcome_counts" in result.evidence
        assert result.evidence["outcome_counts"]["matched"] == 3
        assert result.evidence["outcome_counts"]["deviated"] == 1
        assert result.evidence["avg_effectiveness"] is not None

    def test_signals_surface_low_effectiveness(self, adjuster, db, test_block):
        for i in range(4):
            _add_verification(
                db, test_block.id, test_block.tenant_id,
                "partially_matched", effectiveness=0.15, days_ago=i + 1,
            )
        result = adjuster.compute(db, test_block.id)
        assert any("low_avg_effectiveness" in s for s in result.adjustment_signals)

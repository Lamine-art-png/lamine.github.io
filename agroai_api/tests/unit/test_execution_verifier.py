"""Unit tests for ExecutionVerifier — pure computation, no DB needed."""
import pytest
from datetime import datetime, timedelta

from app.services.execution_verifier import (
    ActualExecution,
    ExecutionVerifier,
    PlannedExecution,
    SoilResponse,
    VERIFIER_VERSION,
    DURATION_TOLERANCE_PCT,
    VOLUME_TOLERANCE_PCT,
    MIN_VWC_RESPONSE,
)


@pytest.fixture
def verifier():
    return ExecutionVerifier()


def _plan(
    start: datetime = None,
    duration: float = 60.0,
    volume: float = 50.0,
) -> PlannedExecution:
    return PlannedExecution(
        start=start or datetime(2026, 4, 1, 6, 0, 0),
        duration_min=duration,
        volume_m3=volume,
    )


def _actual(
    start: datetime = None,
    duration: float = None,
    volume: float = None,
    status: str = "completed",
) -> ActualExecution:
    return ActualExecution(
        start=start or datetime(2026, 4, 1, 6, 5, 0),
        duration_min=duration,
        volume_m3=volume,
        status=status,
    )


def _soil(
    pre: float = None,
    post_24h: float = None,
    post_48h: float = None,
    peak: float = None,
    hours_to_peak: float = None,
    pre_stress: float = None,
) -> SoilResponse:
    return SoilResponse(
        pre_vwc=pre,
        pre_stress_risk=pre_stress,
        post_24h_vwc=post_24h,
        post_48h_vwc=post_48h,
        peak_vwc=peak,
        hours_to_peak=hours_to_peak,
    )


# ==================================================================
# Outcome classification
# ==================================================================

class TestOutcomeClassification:
    def test_matched_when_within_tolerance(self, verifier):
        """Perfect execution with good soil response → matched."""
        result = verifier.verify(
            _plan(duration=60, volume=50),
            _actual(duration=63, volume=48, status="completed"),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.27, peak=0.31, hours_to_peak=8),
        )
        assert result.outcome == "matched"
        assert len(result.deviation_reasons) == 0

    def test_cancelled_is_failed(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(status="cancelled"),
            _soil(),
        )
        assert result.outcome == "failed"
        assert "cancelled" in result.deviation_reasons

    def test_no_execution_data_is_failed(self, verifier):
        result = verifier.verify(
            _plan(),
            ActualExecution(status="unknown"),
            _soil(),
        )
        assert result.outcome == "failed"
        assert "no_execution_data" in result.deviation_reasons

    def test_partially_matched_on_duration_deviation(self, verifier):
        """Duration off by 25% → partially_matched."""
        result = verifier.verify(
            _plan(duration=60, volume=50),
            _actual(duration=75, volume=50, status="completed"),  # +25%
            _soil(pre=0.22, post_24h=0.28, post_48h=0.26, peak=0.29, hours_to_peak=6),
        )
        assert result.outcome == "partially_matched"
        assert "duration_excess" in result.deviation_reasons

    def test_deviated_on_major_duration_gap(self, verifier):
        """Duration off by 60% → deviated."""
        result = verifier.verify(
            _plan(duration=60, volume=50),
            _actual(duration=96, volume=50, status="completed"),  # +60%
            _soil(pre=0.22, post_24h=0.28),
        )
        assert result.outcome == "deviated"

    def test_deviated_on_major_volume_gap(self, verifier):
        """Volume off by 55% → deviated."""
        result = verifier.verify(
            _plan(duration=60, volume=50),
            _actual(duration=60, volume=22.5, status="completed"),  # -55%
            _soil(pre=0.22, post_24h=0.28),
        )
        assert result.outcome == "deviated"
        assert "volume_short" in result.deviation_reasons

    def test_agronomically_ineffective(self, verifier):
        """Irrigation ran fine but soil didn't respond."""
        result = verifier.verify(
            _plan(duration=60, volume=50),
            _actual(duration=60, volume=50, status="completed"),
            _soil(pre=0.25, post_24h=0.251, post_48h=0.249, peak=0.252, hours_to_peak=4),
        )
        assert result.outcome == "agronomically_ineffective"
        assert "no_soil_response" in result.deviation_reasons

    def test_delayed_start_flagged(self, verifier):
        """Start delayed by 45 minutes → partially_matched with reason."""
        planned_start = datetime(2026, 4, 1, 6, 0, 0)
        actual_start = planned_start + timedelta(minutes=45)
        result = verifier.verify(
            _plan(start=planned_start, duration=60, volume=50),
            _actual(start=actual_start, duration=60, volume=50, status="completed"),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.27, peak=0.31, hours_to_peak=8),
        )
        assert "delayed_start" in result.deviation_reasons
        assert result.start_delay_minutes == pytest.approx(45.0, abs=0.1)


# ==================================================================
# Deviation percentages
# ==================================================================

class TestDeviations:
    def test_duration_deviation_calculated(self, verifier):
        result = verifier.verify(
            _plan(duration=60),
            _actual(duration=72, volume=50),  # +20%
            _soil(pre=0.22, post_24h=0.28),
        )
        assert result.duration_deviation_pct == pytest.approx(20.0, abs=0.1)

    def test_volume_deviation_calculated(self, verifier):
        result = verifier.verify(
            _plan(volume=50),
            _actual(duration=60, volume=40),  # -20%
            _soil(pre=0.22, post_24h=0.28),
        )
        assert result.volume_deviation_pct == pytest.approx(-20.0, abs=0.1)

    def test_no_deviation_when_actual_missing(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=None),
            _soil(pre=0.22, post_24h=0.28),
        )
        assert result.volume_deviation_pct is None

    def test_duration_short_flagged(self, verifier):
        result = verifier.verify(
            _plan(duration=60),
            _actual(duration=45, volume=50),  # -25%
            _soil(pre=0.22, post_24h=0.28),
        )
        assert "duration_short" in result.deviation_reasons


# ==================================================================
# Soil response
# ==================================================================

class TestSoilResponse:
    def test_vwc_delta_24h(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30),
        )
        assert result.vwc_delta_24h == pytest.approx(0.08, abs=0.001)

    def test_vwc_delta_48h(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.27),
        )
        assert result.vwc_delta_48h == pytest.approx(0.05, abs=0.001)

    def test_no_soil_response_detected(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.25, post_24h=0.255),  # <MIN_VWC_RESPONSE
        )
        assert "no_soil_response" in result.deviation_reasons

    def test_peak_vwc_reported(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30, peak=0.33, hours_to_peak=6.0),
        )
        assert result.peak_vwc == pytest.approx(0.33, abs=0.001)
        assert result.hours_to_peak == pytest.approx(6.0, abs=0.1)


# ==================================================================
# Verification status
# ==================================================================

class TestVerificationStatus:
    def test_complete_with_all_data(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.27),
        )
        assert result.verification_status == "complete"

    def test_pending_48h_without_48h_data(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30),
        )
        assert result.verification_status == "pending_48h"

    def test_pending_24h_with_only_pre(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22),
        )
        assert result.verification_status == "pending_24h"

    def test_insufficient_data_with_no_soil(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(),
        )
        assert result.verification_status == "insufficient_data"


# ==================================================================
# Confidence
# ==================================================================

class TestConfidence:
    def test_high_confidence_with_full_data(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.27, peak=0.31),
        )
        assert result.confidence > 0.7

    def test_low_confidence_with_missing_actuals(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=None, volume=None),
            _soil(pre=0.22, post_24h=0.30),
        )
        assert result.confidence < 0.5

    def test_low_confidence_with_no_soil_data(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(),
        )
        assert result.confidence < 0.4


# ==================================================================
# Effectiveness score
# ==================================================================

class TestEffectiveness:
    def test_high_effectiveness_with_good_response(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30, post_48h=0.28, peak=0.32, hours_to_peak=6),
        )
        assert result.effectiveness_score is not None
        assert result.effectiveness_score > 0.7

    def test_moderate_effectiveness_with_partial_retention(self, verifier):
        """Good 24h response but poor 48h retention → still scores well on other axes."""
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.28, post_48h=0.23, peak=0.29, hours_to_peak=4),
        )
        assert result.effectiveness_score is not None
        assert 0.5 < result.effectiveness_score <= 1.0

    def test_zero_effectiveness_with_no_response(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.25, post_24h=0.252, post_48h=0.248, peak=0.253, hours_to_peak=2),
        )
        assert result.effectiveness_score is not None
        assert result.effectiveness_score < 0.3

    def test_none_effectiveness_without_soil_data(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(),
        )
        assert result.effectiveness_score is None


# ==================================================================
# Version
# ==================================================================

class TestMeta:
    def test_verifier_version(self, verifier):
        result = verifier.verify(
            _plan(),
            _actual(duration=60, volume=50),
            _soil(pre=0.22, post_24h=0.30),
        )
        assert result.verifier_version == VERIFIER_VERSION

"""Unit tests for ScheduleMatcher — pure computation, no DB needed."""
import pytest
from datetime import datetime, timedelta

from app.services.schedule_matcher import (
    MatchCandidate,
    MatchTarget,
    ScheduleMatcher,
    MIN_MATCH_CONFIDENCE,
    TIME_WINDOW_HOURS,
)


@pytest.fixture
def matcher():
    return ScheduleMatcher()


def _target(
    block_id: str = "block-001",
    start: datetime = None,
    duration: float = 60.0,
    volume: float = 50.0,
    provider_event_id: str = None,
) -> MatchTarget:
    return MatchTarget(
        decision_run_id="dr-001",
        block_id=block_id,
        planned_start=start or datetime(2026, 4, 1, 6, 0, 0),
        planned_duration_min=duration,
        planned_volume_m3=volume,
        provider_event_id=provider_event_id,
    )


def _candidate(
    schedule_id: str = "sched-001",
    block_id: str = "block-001",
    start: datetime = None,
    duration: float = 60.0,
    volume: float = None,
    status: str = "completed",
    provider_schedule_id: str = None,
) -> MatchCandidate:
    return MatchCandidate(
        schedule_id=schedule_id,
        block_id=block_id,
        start_time=start or datetime(2026, 4, 1, 6, 5, 0),
        duration_min=duration,
        volume_m3=volume,
        status=status,
        provider="wiseconn",
        provider_schedule_id=provider_schedule_id,
    )


# ==================================================================
# Basic matching
# ==================================================================

class TestBasicMatching:
    def test_no_candidates_returns_not_matched(self, matcher):
        result = matcher.match(_target(), [])
        assert not result.matched
        assert result.reason == "no_candidates"

    def test_wrong_block_returns_not_matched(self, matcher):
        result = matcher.match(
            _target(block_id="block-001"),
            [_candidate(block_id="block-999")],
        )
        assert not result.matched
        assert result.reason == "no_candidates_for_block"

    def test_all_cancelled_returns_not_matched(self, matcher):
        result = matcher.match(
            _target(),
            [_candidate(status="cancelled")],
        )
        assert not result.matched
        assert result.reason == "all_candidates_cancelled"

    def test_close_time_matches(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t),
            [_candidate(start=t + timedelta(minutes=10), duration=60)],
        )
        assert result.matched
        assert result.confidence > MIN_MATCH_CONFIDENCE

    def test_far_time_does_not_match(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t),
            [_candidate(start=t + timedelta(hours=10))],
        )
        assert not result.matched


# ==================================================================
# Provider ID matching
# ==================================================================

class TestProviderIdMatching:
    def test_exact_provider_id_match(self, matcher):
        result = matcher.match(
            _target(provider_event_id="wc-12345"),
            [_candidate(provider_schedule_id="wc-12345")],
        )
        assert result.matched
        assert result.confidence >= 0.95
        assert result.method == "provider_id"

    def test_provider_id_takes_priority_over_time(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, provider_event_id="wc-12345"),
            [
                # Closer in time but wrong provider ID
                _candidate(schedule_id="s1", start=t + timedelta(minutes=1)),
                # Further in time but correct provider ID
                _candidate(
                    schedule_id="s2",
                    start=t + timedelta(hours=3),
                    provider_schedule_id="wc-12345",
                ),
            ],
        )
        assert result.matched
        assert result.schedule_id == "s2"
        assert result.method == "provider_id"


# ==================================================================
# Time + duration matching
# ==================================================================

class TestTimeDurationMatching:
    def test_close_time_and_duration_scores_higher(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, duration=60),
            [_candidate(start=t + timedelta(minutes=5), duration=62)],
        )
        assert result.matched
        assert result.method == "time_duration"
        assert result.confidence > 0.5

    def test_close_time_far_duration_scores_lower(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        r1 = matcher.match(
            _target(start=t, duration=60),
            [_candidate(start=t + timedelta(minutes=5), duration=62)],
        )
        r2 = matcher.match(
            _target(start=t, duration=60),
            [_candidate(start=t + timedelta(minutes=5), duration=120)],
        )
        assert r1.confidence > r2.confidence

    def test_volume_proximity_adds_confidence(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        r_no_vol = matcher.match(
            _target(start=t, duration=60, volume=50),
            [_candidate(start=t + timedelta(minutes=5), duration=60, volume=None)],
        )
        r_with_vol = matcher.match(
            _target(start=t, duration=60, volume=50),
            [_candidate(start=t + timedelta(minutes=5), duration=60, volume=48)],
        )
        assert r_with_vol.confidence > r_no_vol.confidence


# ==================================================================
# Ambiguity detection
# ==================================================================

class TestAmbiguity:
    def test_two_close_candidates_flagged_ambiguous(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, duration=60),
            [
                _candidate(schedule_id="s1", start=t + timedelta(minutes=5), duration=60),
                _candidate(schedule_id="s2", start=t + timedelta(minutes=7), duration=60),
            ],
        )
        assert result.matched
        assert result.ambiguous

    def test_one_clearly_better_not_ambiguous(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, duration=60),
            [
                _candidate(schedule_id="s1", start=t + timedelta(minutes=5), duration=60),
                _candidate(schedule_id="s2", start=t + timedelta(hours=3), duration=120),
            ],
        )
        assert result.matched
        assert not result.ambiguous
        assert result.schedule_id == "s1"


# ==================================================================
# Best candidate selection
# ==================================================================

class TestBestSelection:
    def test_picks_highest_confidence(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, duration=60),
            [
                _candidate(schedule_id="far", start=t + timedelta(hours=3), duration=60),
                _candidate(schedule_id="close", start=t + timedelta(minutes=2), duration=60),
            ],
        )
        assert result.schedule_id == "close"

    def test_picks_provider_id_over_time(self, matcher):
        t = datetime(2026, 4, 1, 6, 0, 0)
        result = matcher.match(
            _target(start=t, provider_event_id="exact-match"),
            [
                _candidate(schedule_id="time-close", start=t + timedelta(minutes=1)),
                _candidate(
                    schedule_id="id-match",
                    start=t + timedelta(hours=2),
                    provider_schedule_id="exact-match",
                ),
            ],
        )
        assert result.schedule_id == "id-match"

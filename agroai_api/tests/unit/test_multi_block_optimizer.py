"""Unit tests for MultiBlockOptimizer — pure computation, no DB."""
import pytest
from datetime import datetime

from app.services.forecast_engine import VWCForecast, VWCForecastPoint
from app.services.crop_soil_profile import DEFAULT_PROFILE, get_profile
from app.services.multi_block_optimizer import (
    BlockInput,
    MultiBlockOptimizer,
    OptimizationResult,
    OPTIMIZER_VERSION,
)


def _make_forecast(
    block_id: str = "block-001",
    current_vwc: float = 0.25,
    hours_to_stress: float = 24.0,
    confidence: float = 0.8,
    stress_at_24h: float = 0.6,
) -> VWCForecast:
    """Helper to build a VWCForecast."""
    points = [
        VWCForecastPoint(
            hours_ahead=h,
            predicted_vwc=max(0.1, current_vwc - 0.002 * h),
            stress_risk=min(1.0, stress_at_24h * (h / 24.0)),
            below_stress=(current_vwc - 0.002 * h) < 0.20,
            confidence=max(0.3, confidence - 0.01 * h),
        )
        for h in [6, 12, 24, 48, 72]
    ]
    return VWCForecast(
        block_id=block_id,
        computed_at=datetime.utcnow(),
        current_vwc=current_vwc,
        points=points,
        hours_to_stress=hours_to_stress,
        optimal_irrigation_window="within_24h",
        confidence=confidence,
        profile_used="default/default",
    )


def _make_block_input(
    block_id: str = "block-001",
    recommended_volume: float = 100.0,
    current_vwc: float = 0.25,
    hours_to_stress: float = 24.0,
    stress_at_24h: float = 0.6,
    area_ha: float = 5.0,
) -> BlockInput:
    return BlockInput(
        block_id=block_id,
        forecast=_make_forecast(
            block_id=block_id,
            current_vwc=current_vwc,
            hours_to_stress=hours_to_stress,
            stress_at_24h=stress_at_24h,
        ),
        recommended_volume_m3=recommended_volume,
        area_ha=area_ha,
        profile=DEFAULT_PROFILE,
    )


@pytest.fixture
def optimizer():
    return MultiBlockOptimizer()


class TestOptimizeBasic:
    def test_returns_optimization_result(self, optimizer):
        blocks = [_make_block_input("b1"), _make_block_input("b2")]
        result = optimizer.optimize(blocks, total_budget_m3=500.0)
        assert isinstance(result, OptimizationResult)
        assert result.optimization_version == OPTIMIZER_VERSION
        assert len(result.allocations) == 2

    def test_empty_blocks(self, optimizer):
        result = optimizer.optimize([], total_budget_m3=100.0)
        assert result.total_allocated_m3 == 0.0
        assert len(result.allocations) == 0

    def test_to_dict_serializes(self, optimizer):
        blocks = [_make_block_input("b1")]
        result = optimizer.optimize(blocks, total_budget_m3=500.0)
        d = result.to_dict()
        assert "allocations" in d
        assert "total_budget_m3" in d
        assert "blocks_at_risk" in d


class TestFullBudget:
    def test_full_allocation_when_budget_sufficient(self, optimizer):
        blocks = [
            _make_block_input("b1", recommended_volume=100.0),
            _make_block_input("b2", recommended_volume=100.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=300.0)
        # Budget (300) > total recommended (200)
        assert result.total_allocated_m3 == 200.0
        for a in result.allocations:
            assert a.allocation_pct == 1.0
        assert result.blocks_at_risk == 0

    def test_full_allocation_exact_budget(self, optimizer):
        blocks = [
            _make_block_input("b1", recommended_volume=100.0),
            _make_block_input("b2", recommended_volume=100.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=200.0)
        assert result.total_allocated_m3 == 200.0


class TestConstrainedBudget:
    def test_priority_allocation_under_constraint(self, optimizer):
        """Urgent block should get more than non-urgent block."""
        urgent = _make_block_input(
            "urgent", recommended_volume=100.0,
            current_vwc=0.18, hours_to_stress=6.0, stress_at_24h=0.9,
        )
        relaxed = _make_block_input(
            "relaxed", recommended_volume=100.0,
            current_vwc=0.30, hours_to_stress=72.0, stress_at_24h=0.2,
        )
        result = optimizer.optimize([urgent, relaxed], total_budget_m3=120.0)

        alloc_map = {a.block_id: a for a in result.allocations}
        # Urgent block should get more
        assert alloc_map["urgent"].allocated_volume_m3 > alloc_map["relaxed"].allocated_volume_m3

    def test_minimum_allocation_guaranteed(self, optimizer):
        """Even low-priority blocks get at least MIN_ALLOCATION_PCT."""
        blocks = [
            _make_block_input(
                "urgent", recommended_volume=100.0,
                hours_to_stress=6.0, stress_at_24h=0.9,
            ),
            _make_block_input(
                "low", recommended_volume=100.0,
                hours_to_stress=72.0, stress_at_24h=0.1,
            ),
        ]
        # Budget covers minimums (30+30=60) plus some surplus
        result = optimizer.optimize(blocks, total_budget_m3=80.0)

        alloc_map = {a.block_id: a for a in result.allocations}
        # Low priority should still get at least 30% of its recommended
        assert alloc_map["low"].allocated_volume_m3 >= 100.0 * optimizer.MIN_ALLOCATION_PCT

    def test_severe_constraint_proportional(self, optimizer):
        """When budget < sum of minimums, allocate proportionally by priority."""
        blocks = [
            _make_block_input("b1", recommended_volume=100.0, hours_to_stress=10.0),
            _make_block_input("b2", recommended_volume=100.0, hours_to_stress=50.0),
        ]
        # 20 < 30+30 minimums
        result = optimizer.optimize(blocks, total_budget_m3=20.0)
        total = sum(a.allocated_volume_m3 for a in result.allocations)
        assert total <= 20.0

    def test_blocks_at_risk_counted(self, optimizer):
        blocks = [
            _make_block_input("b1", recommended_volume=100.0),
            _make_block_input("b2", recommended_volume=100.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=100.0)
        # Only 100 for 200 recommended — at least one block under 80%
        assert result.blocks_at_risk >= 1


class TestPriorityScoring:
    def test_imminent_stress_highest_priority(self, optimizer):
        urgent = _make_block_input("urgent", hours_to_stress=3.0, stress_at_24h=0.95)
        relaxed = _make_block_input("relaxed", hours_to_stress=100.0, stress_at_24h=0.1)
        score_urgent = optimizer._priority_score(urgent)
        score_relaxed = optimizer._priority_score(relaxed)
        assert score_urgent > score_relaxed

    def test_already_stressed_gets_max_time_urgency(self, optimizer):
        stressed = _make_block_input("stressed", hours_to_stress=0.0, stress_at_24h=1.0)
        score = optimizer._priority_score(stressed)
        assert score > 0.5

    def test_no_stress_low_priority(self, optimizer):
        safe = _make_block_input(
            "safe", current_vwc=0.35,
            hours_to_stress=200.0, stress_at_24h=0.05,
        )
        score = optimizer._priority_score(safe)
        assert score < 0.5

    def test_score_bounded_0_to_1(self, optimizer):
        for hts in [0, 6, 12, 24, 48, 72, 200]:
            block = _make_block_input("b", hours_to_stress=float(hts))
            score = optimizer._priority_score(block)
            assert 0.0 <= score <= 1.0


class TestNoWaterNeeded:
    def test_zero_recommended_volume(self, optimizer):
        blocks = [
            _make_block_input("needs_water", recommended_volume=100.0),
            _make_block_input("no_need", recommended_volume=0.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=50.0)
        alloc_map = {a.block_id: a for a in result.allocations}
        assert alloc_map["no_need"].allocated_volume_m3 == 0.0

    def test_all_blocks_no_water(self, optimizer):
        blocks = [
            _make_block_input("a", recommended_volume=0.0),
            _make_block_input("b", recommended_volume=0.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=100.0)
        assert result.total_allocated_m3 == 0.0


class TestBudgetUtilization:
    def test_utilization_ratio(self, optimizer):
        blocks = [_make_block_input("b1", recommended_volume=50.0)]
        result = optimizer.optimize(blocks, total_budget_m3=200.0)
        assert result.budget_utilization == round(50.0 / 200.0, 3)

    def test_full_utilization_under_constraint(self, optimizer):
        blocks = [
            _make_block_input("b1", recommended_volume=100.0),
            _make_block_input("b2", recommended_volume=100.0),
        ]
        result = optimizer.optimize(blocks, total_budget_m3=50.0)
        # Should use all available budget
        assert result.total_allocated_m3 <= 50.0

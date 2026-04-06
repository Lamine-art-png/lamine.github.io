"""Multi-block water budget optimizer — Phase 5.

Given a set of blocks with forecasts, recommendations, and a total
water budget, optimizes irrigation allocation across blocks to:
1. Minimize total crop stress risk
2. Respect water budget constraints
3. Prioritize blocks approaching stress threshold

Algorithm: greedy priority-queue allocation, not LP/MILP.
Explicit, testable, no ML in the decision path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.services.forecast_engine import VWCForecast
from app.services.crop_soil_profile import CropSoilProfile, DEFAULT_PROFILE

logger = logging.getLogger(__name__)

OPTIMIZER_VERSION = "mbo-1.0.0"


@dataclass
class BlockAllocation:
    """Optimized irrigation allocation for a single block."""
    block_id: str
    priority_score: float       # 0-1, higher = more urgent
    recommended_volume_m3: float
    allocated_volume_m3: float  # After budget optimization
    allocation_pct: float       # % of recommended that was allocated
    stress_risk: float          # Current stress risk
    hours_to_stress: Optional[float]
    rationale: str              # Human-readable reason for allocation


@dataclass
class OptimizationResult:
    """Result of multi-block water budget optimization."""
    computed_at: datetime
    total_budget_m3: float
    total_allocated_m3: float
    total_recommended_m3: float
    budget_utilization: float   # allocated / budget
    allocations: List[BlockAllocation]
    blocks_at_risk: int         # Blocks where allocation < 80% of recommended
    optimization_version: str = OPTIMIZER_VERSION

    def to_dict(self) -> Dict:
        return {
            "computed_at": self.computed_at.isoformat(),
            "total_budget_m3": self.total_budget_m3,
            "total_allocated_m3": self.total_allocated_m3,
            "total_recommended_m3": self.total_recommended_m3,
            "budget_utilization": self.budget_utilization,
            "allocations": [
                {
                    "block_id": a.block_id,
                    "priority_score": a.priority_score,
                    "recommended_volume_m3": a.recommended_volume_m3,
                    "allocated_volume_m3": a.allocated_volume_m3,
                    "allocation_pct": a.allocation_pct,
                    "stress_risk": a.stress_risk,
                    "hours_to_stress": a.hours_to_stress,
                    "rationale": a.rationale,
                }
                for a in self.allocations
            ],
            "blocks_at_risk": self.blocks_at_risk,
            "optimization_version": self.optimization_version,
        }


@dataclass
class BlockInput:
    """Input for a single block to the optimizer."""
    block_id: str
    forecast: VWCForecast
    recommended_volume_m3: float
    area_ha: float
    profile: CropSoilProfile = field(default_factory=lambda: DEFAULT_PROFILE)


class MultiBlockOptimizer:
    """Stateless optimizer: block inputs + budget → allocation plan.

    Algorithm:
    1. Score each block by urgency (stress risk, hours to stress, forecast trajectory)
    2. Sort by priority (highest urgency first)
    3. Allocate budget greedily: full allocation to highest priority blocks
    4. When budget runs low, proportionally reduce allocation for lower-priority blocks
    5. Ensure minimum allocation (30%) for any block that needs water
    """

    MIN_ALLOCATION_PCT = 0.30   # Minimum allocation as fraction of recommended

    def optimize(
        self,
        blocks: List[BlockInput],
        total_budget_m3: float,
    ) -> OptimizationResult:
        """Optimize water allocation across blocks."""
        now = datetime.utcnow()

        if not blocks:
            return OptimizationResult(
                computed_at=now,
                total_budget_m3=total_budget_m3,
                total_allocated_m3=0.0,
                total_recommended_m3=0.0,
                budget_utilization=0.0,
                allocations=[],
                blocks_at_risk=0,
            )

        # Score and sort blocks by urgency
        scored = [(b, self._priority_score(b)) for b in blocks]
        scored.sort(key=lambda x: x[1], reverse=True)

        total_recommended = sum(b.recommended_volume_m3 for b in blocks)

        # If budget covers everything, allocate fully
        if total_budget_m3 >= total_recommended:
            allocations = [
                BlockAllocation(
                    block_id=b.block_id,
                    priority_score=round(score, 3),
                    recommended_volume_m3=round(b.recommended_volume_m3, 2),
                    allocated_volume_m3=round(b.recommended_volume_m3, 2),
                    allocation_pct=1.0,
                    stress_risk=round(b.forecast.confidence, 3),
                    hours_to_stress=b.forecast.hours_to_stress,
                    rationale="Full allocation — budget sufficient",
                )
                for b, score in scored
            ]
            return OptimizationResult(
                computed_at=now,
                total_budget_m3=round(total_budget_m3, 2),
                total_allocated_m3=round(total_recommended, 2),
                total_recommended_m3=round(total_recommended, 2),
                budget_utilization=round(total_recommended / total_budget_m3, 3) if total_budget_m3 > 0 else 0.0,
                allocations=allocations,
                blocks_at_risk=0,
            )

        # Budget-constrained: greedy allocation by priority
        allocations = self._constrained_allocation(scored, total_budget_m3)

        total_allocated = sum(a.allocated_volume_m3 for a in allocations)
        blocks_at_risk = sum(1 for a in allocations if a.allocation_pct < 0.8)

        return OptimizationResult(
            computed_at=now,
            total_budget_m3=round(total_budget_m3, 2),
            total_allocated_m3=round(total_allocated, 2),
            total_recommended_m3=round(total_recommended, 2),
            budget_utilization=round(total_allocated / total_budget_m3, 3) if total_budget_m3 > 0 else 0.0,
            allocations=allocations,
            blocks_at_risk=blocks_at_risk,
        )

    def _priority_score(self, block: BlockInput) -> float:
        """Score a block's irrigation urgency (0-1, higher = more urgent).

        Components:
        - Stress proximity: how close to stress threshold (from forecast)
        - Time urgency: fewer hours to stress = higher priority
        - Forecast confidence: higher confidence forecasts get slight priority
        """
        fc = block.forecast

        # Stress proximity from forecast points
        # Use the 24h forecast point as primary signal
        stress_at_24h = 0.0
        for p in fc.points:
            if p.hours_ahead == 24:
                stress_at_24h = p.stress_risk
                break

        # Time urgency: hours_to_stress → urgency score
        time_urgency = 0.0
        if fc.hours_to_stress is not None:
            if fc.hours_to_stress <= 0:
                time_urgency = 1.0
            elif fc.hours_to_stress <= 12:
                time_urgency = 0.9
            elif fc.hours_to_stress <= 24:
                time_urgency = 0.7
            elif fc.hours_to_stress <= 48:
                time_urgency = 0.4
            elif fc.hours_to_stress <= 72:
                time_urgency = 0.2
            else:
                time_urgency = 0.1

        # Current VWC deficit from field capacity
        profile = block.profile
        vwc_range = profile.field_capacity - profile.wilting_point
        if vwc_range > 0:
            deficit_score = max(0.0, min(1.0,
                (profile.field_capacity - fc.current_vwc) / vwc_range
            ))
        else:
            deficit_score = 0.5

        # Combine: time urgency dominates, stress and deficit support
        score = (
            time_urgency * 0.45 +
            stress_at_24h * 0.30 +
            deficit_score * 0.25
        )

        # Confidence boost: slightly prefer higher-confidence forecasts
        score *= (0.8 + 0.2 * fc.confidence)

        return max(0.0, min(1.0, score))

    def _constrained_allocation(
        self,
        scored: List[tuple],
        budget: float,
    ) -> List[BlockAllocation]:
        """Allocate budget greedily with minimum allocation guarantee.

        Strategy:
        1. Reserve minimum allocation (30%) for all blocks that need water
        2. Distribute remaining budget by priority order
        """
        # Filter blocks that actually need water
        needs_water = [(b, s) for b, s in scored if b.recommended_volume_m3 > 0]
        no_water = [(b, s) for b, s in scored if b.recommended_volume_m3 <= 0]

        if not needs_water:
            return [
                BlockAllocation(
                    block_id=b.block_id,
                    priority_score=round(s, 3),
                    recommended_volume_m3=0.0,
                    allocated_volume_m3=0.0,
                    allocation_pct=1.0,
                    stress_risk=0.0,
                    hours_to_stress=b.forecast.hours_to_stress,
                    rationale="No irrigation needed",
                )
                for b, s in no_water
            ]

        # Calculate minimum reserves
        min_reserves = {
            b.block_id: b.recommended_volume_m3 * self.MIN_ALLOCATION_PCT
            for b, _ in needs_water
        }
        total_min = sum(min_reserves.values())

        allocations = []

        if budget < total_min:
            # Can't even meet minimums — allocate proportionally by priority
            total_priority = sum(s for _, s in needs_water) or 1.0
            for b, score in needs_water:
                share = (score / total_priority) * budget
                alloc_pct = share / b.recommended_volume_m3 if b.recommended_volume_m3 > 0 else 0.0
                allocations.append(BlockAllocation(
                    block_id=b.block_id,
                    priority_score=round(score, 3),
                    recommended_volume_m3=round(b.recommended_volume_m3, 2),
                    allocated_volume_m3=round(share, 2),
                    allocation_pct=round(alloc_pct, 3),
                    stress_risk=round(score, 3),
                    hours_to_stress=b.forecast.hours_to_stress,
                    rationale=f"Severe budget constraint — {alloc_pct*100:.0f}% of recommended",
                ))
        else:
            # Guarantee minimums, then allocate surplus by priority
            remaining = budget - total_min
            alloc_map = dict(min_reserves)

            for b, score in needs_water:
                additional_needed = b.recommended_volume_m3 - min_reserves[b.block_id]
                if additional_needed <= 0:
                    continue
                give = min(additional_needed, remaining)
                alloc_map[b.block_id] += give
                remaining -= give
                if remaining <= 0:
                    break

            for b, score in needs_water:
                allocated = alloc_map[b.block_id]
                alloc_pct = allocated / b.recommended_volume_m3 if b.recommended_volume_m3 > 0 else 0.0

                if alloc_pct >= 0.95:
                    rationale = "Full allocation"
                elif alloc_pct >= 0.8:
                    rationale = "Near-full allocation"
                elif alloc_pct >= self.MIN_ALLOCATION_PCT:
                    rationale = f"Reduced to {alloc_pct*100:.0f}% — budget constraint"
                else:
                    rationale = f"Minimum allocation ({alloc_pct*100:.0f}%)"

                allocations.append(BlockAllocation(
                    block_id=b.block_id,
                    priority_score=round(score, 3),
                    recommended_volume_m3=round(b.recommended_volume_m3, 2),
                    allocated_volume_m3=round(allocated, 2),
                    allocation_pct=round(alloc_pct, 3),
                    stress_risk=round(score, 3),
                    hours_to_stress=b.forecast.hours_to_stress,
                    rationale=rationale,
                ))

        # Add blocks that don't need water
        for b, score in no_water:
            allocations.append(BlockAllocation(
                block_id=b.block_id,
                priority_score=round(score, 3),
                recommended_volume_m3=0.0,
                allocated_volume_m3=0.0,
                allocation_pct=1.0,
                stress_risk=0.0,
                hours_to_stress=b.forecast.hours_to_stress,
                rationale="No irrigation needed",
            ))

        return allocations

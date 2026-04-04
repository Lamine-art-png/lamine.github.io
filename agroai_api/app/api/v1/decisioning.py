"""Decisioning API — water state and irrigation recommendations.

Exposes the Phase 1 decision engine: water state estimation per block,
and water-state-aware irrigation recommendations.
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.base import get_db
from app.models.block import Block
from app.models.water_state import WaterState
from app.services.feature_builder import FeatureBuilder
from app.services.water_state_engine import WaterStateEngine, ENGINE_VERSION
from app.services.recommender import Recommender
from app.schemas.recommendation import (
    ComputeRecommendationRequest,
    IrrigationConstraints,
    IrrigationTargets,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/decisioning", tags=["decisioning"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class WaterStateResponse(BaseModel):
    id: str
    block_id: str
    estimated_at: datetime
    root_zone_vwc: float
    stress_risk: float
    refill_status: str
    depletion_rate: Optional[float] = None
    hours_to_stress: Optional[float] = None
    et_demand_mm_day: Optional[float] = None
    confidence: float
    anomaly_flags: List[str] = []
    engine_version: str


class WaterStateHistoryResponse(BaseModel):
    block_id: str
    states: List[WaterStateResponse]
    count: int


class RecommendationWithStateResponse(BaseModel):
    when: datetime
    duration_min: float
    volume_m3: float
    confidence: float
    explanations: List[str]
    version: str
    water_state: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/blocks/{block_id}/water-state", response_model=WaterStateResponse)
def estimate_water_state(
    block_id: str,
    db: Session = Depends(get_db),
):
    """Compute and persist a water state estimate for a block."""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail=f"Block {block_id} not found")

    builder = FeatureBuilder()
    engine = WaterStateEngine()

    fs = builder.build(db, block_id)
    estimate = engine.estimate(fs)

    # Persist
    ws = WaterState(
        id=str(uuid.uuid4()),
        tenant_id=block.tenant_id,
        block_id=block_id,
        estimated_at=estimate.estimated_at,
        root_zone_vwc=estimate.root_zone_vwc,
        depth_profile=estimate.depth_profile,
        stress_risk=estimate.stress_risk,
        refill_status=estimate.refill_status,
        depletion_rate=estimate.depletion_rate,
        hours_to_stress=estimate.hours_to_stress,
        et_demand_mm_day=estimate.et_demand_mm_day,
        last_irrigation_at=estimate.last_irrigation_at,
        last_irrigation_volume_m3=estimate.last_irrigation_volume_m3,
        confidence=estimate.confidence,
        anomaly_flags=estimate.anomaly_flags,
        feature_snapshot=estimate.feature_snapshot,
        engine_version=estimate.engine_version,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    return WaterStateResponse(
        id=ws.id,
        block_id=ws.block_id,
        estimated_at=ws.estimated_at,
        root_zone_vwc=ws.root_zone_vwc,
        stress_risk=ws.stress_risk,
        refill_status=ws.refill_status,
        depletion_rate=ws.depletion_rate,
        hours_to_stress=ws.hours_to_stress,
        et_demand_mm_day=ws.et_demand_mm_day,
        confidence=ws.confidence,
        anomaly_flags=ws.anomaly_flags or [],
        engine_version=ws.engine_version,
    )


@router.get("/blocks/{block_id}/water-state", response_model=WaterStateResponse)
def get_latest_water_state(
    block_id: str,
    db: Session = Depends(get_db),
):
    """Get the most recent water state estimate for a block."""
    ws = (
        db.query(WaterState)
        .filter(WaterState.block_id == block_id)
        .order_by(desc(WaterState.estimated_at))
        .first()
    )
    if not ws:
        raise HTTPException(
            status_code=404,
            detail=f"No water state found for block {block_id}. POST to compute one.",
        )

    return WaterStateResponse(
        id=ws.id,
        block_id=ws.block_id,
        estimated_at=ws.estimated_at,
        root_zone_vwc=ws.root_zone_vwc,
        stress_risk=ws.stress_risk,
        refill_status=ws.refill_status,
        depletion_rate=ws.depletion_rate,
        hours_to_stress=ws.hours_to_stress,
        et_demand_mm_day=ws.et_demand_mm_day,
        confidence=ws.confidence,
        anomaly_flags=ws.anomaly_flags or [],
        engine_version=ws.engine_version,
    )


@router.get(
    "/blocks/{block_id}/water-state/history",
    response_model=WaterStateHistoryResponse,
)
def get_water_state_history(
    block_id: str,
    limit: int = 24,
    db: Session = Depends(get_db),
):
    """Get recent water state history for a block (default last 24 estimates)."""
    states = (
        db.query(WaterState)
        .filter(WaterState.block_id == block_id)
        .order_by(desc(WaterState.estimated_at))
        .limit(limit)
        .all()
    )

    return WaterStateHistoryResponse(
        block_id=block_id,
        states=[
            WaterStateResponse(
                id=ws.id,
                block_id=ws.block_id,
                estimated_at=ws.estimated_at,
                root_zone_vwc=ws.root_zone_vwc,
                stress_risk=ws.stress_risk,
                refill_status=ws.refill_status,
                depletion_rate=ws.depletion_rate,
                hours_to_stress=ws.hours_to_stress,
                et_demand_mm_day=ws.et_demand_mm_day,
                confidence=ws.confidence,
                anomaly_flags=ws.anomaly_flags or [],
                engine_version=ws.engine_version,
            )
            for ws in states
        ],
        count=len(states),
    )


@router.post(
    "/blocks/{block_id}/recommend",
    response_model=RecommendationWithStateResponse,
)
def compute_recommendation(
    block_id: str,
    request: ComputeRecommendationRequest = None,
    db: Session = Depends(get_db),
):
    """Compute water-state-aware irrigation recommendation for a block."""
    if request is None:
        request = ComputeRecommendationRequest()

    recommender = Recommender()
    result = recommender.compute(
        db=db,
        block_id=block_id,
        constraints=request.constraints,
        targets=request.targets,
        horizon_hours=request.horizon_hours,
    )

    return RecommendationWithStateResponse(**result)


@router.post("/lifecycle-proof")
def run_lifecycle_proof(
    tenant_id: str = "wiseconn-demo",
    db: Session = Depends(get_db),
):
    """Run a full decision lifecycle proof using live synced data."""
    from app.services.lifecycle_proof import prove_lifecycle
    return prove_lifecycle(db, tenant_id)

"""Recommendation API endpoints."""
import logging
import uuid
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.base import get_db
from app.core.security import get_current_tenant_id
from app.core import metrics
from app.schemas.recommendation import (
    ComputeRecommendationRequest,
    RecommendationResponse,
    SimulateScenarioRequest,
    SimulateScenarioResponse,
)
from app.services.recommender import Recommender
from app.services.idempotency import IdempotencyService
from app.services.webhook import WebhookService
from app.services.metering import MeteringService
from app.models.recommendation import Recommendation
from app.models.block import Block

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/blocks/{block_id}/recommendations:compute", response_model=RecommendationResponse)
async def compute_recommendation(
    block_id: str,
    request: ComputeRecommendationRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    Compute irrigation recommendation for a block.

    Supports idempotency via Idempotency-Key header.
    Results cached for 6h based on feature hash.
    """
    # Check if block exists and belongs to tenant
    block = db.query(Block).filter(
        and_(Block.id == block_id, Block.tenant_id == tenant_id)
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    # Compute body hash
    body_dict = request.model_dump()
    body_hash = IdempotencyService.compute_body_hash(body_dict)

    # Check idempotency cache (24h window)
    if idempotency_key:
        cached = IdempotencyService.get_cached_recommendation(
            db, tenant_id, idempotency_key, body_hash
        )
        if cached:
            logger.info(f"Idempotency cache hit for key {idempotency_key}")
            metrics.idempotency_hits.inc()
            return RecommendationResponse.model_validate(cached)

    # Compute features and feature hash
    recommender = Recommender()
    features = recommender._extract_features(db, block_id, request.horizon_hours)
    feature_hash = IdempotencyService.compute_feature_hash(
        block_id, request.horizon_hours, features
    )

    # Check feature cache (6h TTL)
    feature_cached = IdempotencyService.get_feature_cached_recommendation(
        db, block_id, feature_hash
    )
    if feature_cached:
        logger.info(f"Feature cache hit for block {block_id}")
        return RecommendationResponse.model_validate(feature_cached)

    # Compute new recommendation
    with metrics.compute_latency.time():
        result = recommender.compute(
            db=db,
            block_id=block_id,
            constraints=request.constraints,
            targets=request.targets,
            horizon_hours=request.horizon_hours,
        )

    # Save recommendation
    rec = IdempotencyService.save_recommendation(
        db=db,
        tenant_id=tenant_id,
        block_id=block_id,
        result=result,
        idempotency_key=idempotency_key,
        body_hash=body_hash,
        feature_hash=feature_hash,
        horizon_hours=request.horizon_hours,
    )

    # Record metrics
    metrics.recommendations_total.labels(
        tenant=tenant_id,
        status="success"
    ).inc()

    # Record usage metering
    MeteringService.record_usage(
        db=db,
        tenant_id=tenant_id,
        endpoint="/v1/blocks/{id}/recommendations:compute",
        unit="compute",
        quantity=1.0,
        block_id=block_id,
    )

    # Emit webhook
    await WebhookService.emit_event(
        db=db,
        tenant_id=tenant_id,
        event_type="recommendation.created",
        data={
            "recommendation_id": rec.id,
            "block_id": block_id,
            "when": result["when"].isoformat(),
            "duration_min": result["duration_min"],
            "volume_m3": result["volume_m3"],
        }
    )

    return RecommendationResponse.model_validate(rec)


@router.get("/blocks/{block_id}/recommendations", response_model=RecommendationResponse)
def get_recommendation(
    block_id: str,
    date: Optional[date] = None,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Get cached recommendation for a block.

    If date is provided, returns recommendation for that date.
    Otherwise returns most recent recommendation.
    """
    # Check block access
    block = db.query(Block).filter(
        and_(Block.id == block_id, Block.tenant_id == tenant_id)
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    query = db.query(Recommendation).filter(
        and_(
            Recommendation.block_id == block_id,
            Recommendation.tenant_id == tenant_id,
        )
    )

    if date:
        # Find recommendation for specific date
        start = datetime.combine(date, datetime.min.time())
        end = datetime.combine(date, datetime.max.time())
        query = query.filter(
            Recommendation.created_at.between(start, end)
        )

    rec = query.order_by(Recommendation.created_at.desc()).first()

    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommendation found"
        )

    return RecommendationResponse.model_validate(rec)


@router.post("/scenarios:simulate", response_model=SimulateScenarioResponse)
async def simulate_scenario(
    request: SimulateScenarioRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Simulate multi-block irrigation scenario.

    What-if analysis across multiple blocks with shared or per-block constraints.
    """
    # Verify all blocks exist and belong to tenant
    blocks = db.query(Block).filter(
        and_(
            Block.id.in_(request.block_ids),
            Block.tenant_id == tenant_id,
        )
    ).all()

    if len(blocks) != len(request.block_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more blocks not found"
        )

    # Run recommender for each block
    recommender = Recommender()
    recommendations = {}
    total_volume = 0.0

    for block in blocks:
        # Check for per-block overrides
        block_constraints = request.constraints
        block_targets = request.targets

        if request.overrides and block.id in request.overrides:
            override = request.overrides[block.id]
            if "constraints" in override:
                block_constraints = override["constraints"]
            if "targets" in override:
                block_targets = override["targets"]

        result = recommender.compute(
            db=db,
            block_id=block.id,
            constraints=block_constraints,
            targets=block_targets,
            horizon_hours=request.horizon_hours,
        )

        recommendations[block.id] = RecommendationResponse(**result)
        total_volume += result["volume_m3"]

    scenario_id = str(uuid.uuid4())

    # Record metering for scenario
    MeteringService.record_usage(
        db=db,
        tenant_id=tenant_id,
        endpoint="/v1/scenarios:simulate",
        unit="scenario",
        quantity=1.0,
        metadata=f"blocks_count={len(request.block_ids)}",
    )

    return SimulateScenarioResponse(
        scenario_id=scenario_id,
        recommendations=recommendations,
        total_volume_m3=round(total_volume, 2),
        total_cost_estimate=None,  # Could calculate based on water rates
    )

"""Forecast API — VWC forecast, accuracy, crop profiles, optimization.

Endpoints:
- POST /v1/forecast/{block_id}       — Run VWC forecast for a block
- GET  /v1/forecast/{block_id}       — Get latest forecast
- GET  /v1/forecast/accuracy/{block_id} — Forecast accuracy report
- GET  /v1/forecast/profiles         — List available crop/soil profiles
- POST /v1/forecast/optimize         — Multi-block water budget optimization
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.block import Block
from app.models.forecast import Forecast
from app.services.crop_soil_profile import get_profile, list_profiles
from app.services.feature_builder import FeatureBuilder
from app.services.forecast_accuracy import ForecastAccuracyTracker
from app.services.forecast_engine import ForecastEngine
from app.services.multi_block_optimizer import (
    BlockInput,
    MultiBlockOptimizer,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/forecast", tags=["forecast"])


# ── Request / Response models ──────────────────────────────────────

class ForecastRequest(BaseModel):
    crop_type: Optional[str] = None
    soil_type: Optional[str] = None


class OptimizeRequest(BaseModel):
    tenant_id: str
    block_ids: List[str] = Field(..., min_length=1)
    total_budget_m3: float = Field(..., gt=0)
    crop_type: Optional[str] = None
    soil_type: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────

@router.post("/{block_id}", response_model=Dict[str, Any])
def run_forecast(
    block_id: str,
    body: ForecastRequest = ForecastRequest(),
    db: Session = Depends(get_db),
):
    """Run VWC forecast for a block and persist the result."""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail=f"Block {block_id} not found")

    # Resolve profile
    crop = body.crop_type or block.crop_type
    soil = body.soil_type or block.soil_type
    profile = get_profile(crop, soil)

    # Build features and run forecast
    builder = FeatureBuilder()
    engine = ForecastEngine()

    fs = builder.build(db, block_id)
    forecast = engine.forecast(fs, profile)

    # Persist
    fc_record = Forecast(
        id=str(uuid.uuid4()),
        tenant_id=block.tenant_id,
        block_id=block_id,
        computed_at=forecast.computed_at,
        current_vwc=forecast.current_vwc,
        points=[p.__dict__ for p in forecast.points],
        hours_to_stress=forecast.hours_to_stress,
        optimal_irrigation_window=forecast.optimal_irrigation_window,
        confidence=forecast.confidence,
        profile_used=forecast.profile_used,
        forecast_version=forecast.forecast_version,
    )
    db.add(fc_record)
    db.commit()

    result = forecast.to_dict()
    result["forecast_id"] = fc_record.id
    return result


@router.get("/{block_id}", response_model=Dict[str, Any])
def get_latest_forecast(
    block_id: str,
    db: Session = Depends(get_db),
):
    """Get the latest forecast for a block."""
    fc = (
        db.query(Forecast)
        .filter(Forecast.block_id == block_id)
        .order_by(desc(Forecast.computed_at))
        .first()
    )
    if not fc:
        raise HTTPException(status_code=404, detail=f"No forecast for block {block_id}")

    return {
        "forecast_id": fc.id,
        "block_id": fc.block_id,
        "computed_at": fc.computed_at.isoformat(),
        "current_vwc": fc.current_vwc,
        "points": fc.points,
        "hours_to_stress": fc.hours_to_stress,
        "optimal_irrigation_window": fc.optimal_irrigation_window,
        "confidence": fc.confidence,
        "profile_used": fc.profile_used,
        "forecast_version": fc.forecast_version,
    }


@router.get("/accuracy/{block_id}", response_model=Dict[str, Any])
def forecast_accuracy(
    block_id: str,
    lookback_days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Get forecast accuracy report for a block."""
    tracker = ForecastAccuracyTracker()
    summary = tracker.block_accuracy_summary(db, block_id, lookback_days)

    # Also get recent individual reports
    reports = tracker.evaluate(db, block_id, min(lookback_days, 7))

    return {
        "summary": summary,
        "recent_reports": [r.to_dict() for r in reports[:10]],
    }


@router.get("/profiles/all", response_model=List[Dict[str, Any]])
def get_profiles():
    """List all available crop/soil profiles."""
    return list_profiles()


@router.post("/optimize", response_model=Dict[str, Any])
def optimize_allocation(
    body: OptimizeRequest,
    db: Session = Depends(get_db),
):
    """Multi-block water budget optimization.

    Given a set of blocks and a total water budget, returns optimized
    irrigation allocation that minimizes crop stress across blocks.
    """
    builder = FeatureBuilder()
    engine = ForecastEngine()
    optimizer = MultiBlockOptimizer()

    block_inputs: List[BlockInput] = []

    for bid in body.block_ids:
        block = db.query(Block).filter(Block.id == bid).first()
        if not block:
            raise HTTPException(status_code=404, detail=f"Block {bid} not found")

        crop = body.crop_type or block.crop_type
        soil = body.soil_type or block.soil_type
        profile = get_profile(crop, soil)

        fs = builder.build(db, bid)
        forecast = engine.forecast(fs, profile)

        # Estimate recommended volume from deficit
        current_vwc = forecast.current_vwc
        target_vwc = profile.field_capacity * 0.9  # Target 90% of FC
        vwc_deficit = max(0, target_vwc - current_vwc)
        deficit_mm = vwc_deficit * profile.root_depth_mm
        volume_m3 = (deficit_mm / 1000.0) * block.area_ha * 10000 / 0.85

        block_inputs.append(BlockInput(
            block_id=bid,
            forecast=forecast,
            recommended_volume_m3=volume_m3,
            area_ha=block.area_ha,
            profile=profile,
        ))

    result = optimizer.optimize(block_inputs, body.total_budget_m3)
    return result.to_dict()

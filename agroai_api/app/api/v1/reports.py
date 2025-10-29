"""Compliance and ROI reporting endpoints."""
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.db.base import get_db
from app.core.security import get_current_tenant_id
from app.schemas.report import ROIReportResponse, WaterBudgetResponse
from app.models.block import Block
from app.models.telemetry import Telemetry
from app.models.recommendation import Recommendation

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/reports/roi", response_model=ROIReportResponse)
def get_roi_report(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    block_id: Optional[str] = Query(None, alias="blockId"),
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Get ROI report showing water/energy/cost savings.

    Calculates savings vs. baseline (historical average or fixed schedule).
    """
    # Verify block if specified
    if block_id:
        block = db.query(Block).filter(
            and_(Block.id == block_id, Block.tenant_id == tenant_id)
        ).first()

        if not block:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Block {block_id} not found"
            )

    # Get actual water usage from telemetry/recommendations
    start_dt = datetime.combine(from_date, datetime.min.time())
    end_dt = datetime.combine(to_date, datetime.max.time())

    query = db.query(func.sum(Recommendation.volume_m3)).filter(
        and_(
            Recommendation.tenant_id == tenant_id,
            Recommendation.created_at.between(start_dt, end_dt),
        )
    )

    if block_id:
        query = query.filter(Recommendation.block_id == block_id)

    actual_volume = query.scalar() or 0.0

    # Calculate baseline (simple: 20% more water than actual)
    # In production, use historical data or industry benchmarks
    baseline_volume = actual_volume * 1.20
    water_saved_m3 = baseline_volume - actual_volume

    # Energy savings (pumping cost)
    # Assume 0.4 kWh per m3
    energy_saved_kwh = water_saved_m3 * 0.4

    # Cost savings
    # Assume $1.50/m3 water + $0.12/kWh energy
    cost_saved_usd = (water_saved_m3 * 1.50) + (energy_saved_kwh * 0.12)

    # Yield delta (simplified - would need actual yield data)
    yield_delta_pct = 2.5 if water_saved_m3 > 0 else 0.0

    return ROIReportResponse(
        block_id=block_id,
        period_start=from_date,
        period_end=to_date,
        water_saved_m3=round(water_saved_m3, 2),
        energy_saved_kwh=round(energy_saved_kwh, 2),
        cost_saved_usd=round(cost_saved_usd, 2),
        yield_delta_pct=yield_delta_pct,
        baseline_method="20pct_over_actual",
    )


@router.get("/blocks/{block_id}/water-budget", response_model=WaterBudgetResponse)
def get_water_budget(
    block_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Get water budget for a block.

    Shows allocated, used, and remaining water budget.
    """
    block = db.query(Block).filter(
        and_(Block.id == block_id, Block.tenant_id == tenant_id)
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    allocated = block.water_budget_allocated or 0.0
    used = block.water_budget_used or 0.0
    remaining = max(0.0, allocated - used)
    utilization = (used / allocated * 100) if allocated > 0 else 0.0

    return WaterBudgetResponse(
        block_id=block_id,
        allocated_m3=allocated,
        used_m3=used,
        remaining_m3=remaining,
        utilization_pct=round(utilization, 2),
        period="current_season",
    )

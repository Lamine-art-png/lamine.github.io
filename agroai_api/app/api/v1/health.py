# app/api/v1/health.py
"""Health + demo recommendation endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.base import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Basic health check + DB connectivity."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return {
        "status": "ok",
        "database": db_status,
        "version": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Demo recommendation endpoint (for OEMs / pilots)
# ---------------------------------------------------------------------------

class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


@router.post("/demo/recommendation")
async def demo_recommendation(payload: DemoRecommendationRequest):
    """
    Demo endpoint for OEMs / pilots.

    Takes a simple field payload and returns a mocked
    irrigation recommendation + savings estimate.
    """
    # Pick a mid-range savings between 20–35%
    target_savings = 0.275  # 27.5%

    recommended_inches = payload.baseline_inches_per_week * (1 - target_savings)

    return {
        "field_id": payload.field_id,
        "crop": payload.crop,
        "acres": payload.acres,
        "location": payload.location,
        "baseline_inches_per_week": payload.baseline_inches_per_week,
        "recommended_inches_per_week": round(recommended_inches, 2),
        "expected_water_savings_percent": round(target_savings * 100, 1),
        "notes": "Demo-only recommendation for AGRO-AI OEM integration.",
    }


import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import verify_demo_api_key

logger = logging.getLogger(__name__)

# This router will be mounted under the global /v1 prefix
router = APIRouter(
    prefix="/demo",
    tags=["demo"],
    dependencies=[Depends(verify_demo_api_key)],
)


class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


@router.post("/recommendation")
async def demo_recommendation(payload: DemoRecommendationRequest):
    """
    Demo endpoint for OEMs / pilots.

    Takes a simple field payload and returns a mocked
    irrigation recommendation + savings estimate.
    """

    # Pick a mid-range savings between 20–35%
    target_savings = 0.275  # 27.5%
    recommended_inches = payload.baseline_inches_per_week * (1 - target_savings)

    response = {
        "field_id": payload.field_id,
        "crop": payload.crop,
        "acres": payload.acres,
        "location": payload.location,
        "baseline_inches_per_week": payload.baseline_inches_per_week,
        "recommended_inches_per_week": round(recommended_inches, 2),
        "expected_water_savings_percent": round(target_savings * 100, 1),
        "notes": "Demo-only recommendation for AGRO-AI OEM integration.",
    }

    # Structured log for every demo recommendation
    logger.info(
        "demo_recommendation",
        extra={
            "field_id": payload.field_id,
            "crop": payload.crop,
            "acres": payload.acres,
            "location": payload.location,
            "baseline_inches_per_week": payload.baseline_inches_per_week,
            "recommended_inches_per_week": response["recommended_inches_per_week"],
            "expected_water_savings_percent": response[
                "expected_water_savings_percent"
            ],
        },
    )

    return response


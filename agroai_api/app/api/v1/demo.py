from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoRecommendationRequest(BaseModel):
    field_id: str = Field(..., example="block-7")
    crop: str = Field(..., example="vineyard")
    acres: float = Field(..., example=12.5)
    location: str = Field(..., example="Napa, CA")
    baseline_inches_per_week: float = Field(..., example=1.6)


class DemoRecommendationResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    estimated_water_savings_pct: float
    season: str
    version: str
    generated_at: date


@router.post(
    "/recommendation",
    response_model=DemoRecommendationResponse,
    summary="Demo irrigation recommendation",
    description="Deterministic demo endpoint for OEMs / pilots.",
)
async def demo_recommendation(payload: DemoRecommendationRequest) -> DemoRecommendationResponse:
    # Toy logic: fixed ~25% savings
    savings_pct = 0.25
    recommended = payload.baseline_inches_per_week * (1 - savings_pct)

    return DemoRecommendationResponse(
        field_id=payload.field_id,
        crop=payload.crop,
        acres=payload.acres,
        location=payload.location,
        baseline_inches_per_week=payload.baseline_inches_per_week,
        recommended_inches_per_week=round(recommended, 2),
        estimated_water_savings_pct=round(savings_pct * 100, 1),
        season="demo",
        version="1.0.0-demo",
        generated_at=date.today(),
    )


from typing import List

from fastapi import FastAPI
from pydantic import BaseModel


API_VERSION = "1.1.0"


app = FastAPI(
    title="AGRO-AI API",
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# --------- Health endpoint ---------


@app.get("/v1/health")
async def health():
    """
    Simple health check used by ECS and external monitors.
    """
    return {
        "status": "ok",
        "database": "ok",  # placeholder – not actually checking DB here
        "version": API_VERSION,
    }


# --------- Demo recommendation models ---------


class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoRecommendationBlock(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    agroai_inches_per_week: float
    water_savings_percent: float
    notes: str | None = None


class DemoRecommendationResponse(BaseModel):
    status: str
    blocks: List[DemoRecommendationBlock]


# --------- Demo recommendation endpoint ---------


@app.post("/v1/demo/recommendation", response_model=DemoRecommendationResponse)
async def demo_recommendation(
    payload: DemoRecommendationRequest,
) -> DemoRecommendationResponse:
    """
    Tiny demo endpoint:
    - takes a single field
    - pretends AGRO-AI saves ~30% water vs baseline
    """

    baseline = payload.baseline_inches_per_week
    # pretend AGRO-AI saves 30%
    agroai = round(baseline * 0.7, 2)

    savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

    block = DemoRecommendationBlock(
        field_id=payload.field_id,
        crop=payload.crop,
        acres=payload.acres,
        location=payload.location,
        baseline_inches_per_week=baseline,
        agroai_inches_per_week=agroai,
        water_savings_percent=savings_pct,
        notes="Demo-only recommendation for OEM integration.",
    )

    return DemoRecommendationResponse(status="ok", blocks=[block])


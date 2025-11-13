from fastapi import APIRouter
from pydantic import BaseModel

api_router = APIRouter()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@api_router.get("/health", summary="API health check")
async def health():
    return {
        "status": "ok",
        "database": "ok",
        "version": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Demo recommendation endpoint (mounted under /v1 via settings.API_V1_PREFIX)
# Final path: /v1/demo/recommendation
# ---------------------------------------------------------------------------
class DemoRecommendationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


@api_router.post("/demo/recommendation", summary="Demo irrigation recommendation")
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


# ---------------------------------------------------------------------------
# Debug: list v1 routes
# Hit:  GET /v1/debug/routes
# ---------------------------------------------------------------------------
@api_router.get("/debug/routes", summary="List v1 routes (debug)")
async def debug_routes():
    return [
        {
            "path": route.path,
            "name": route.name,
            "methods": list(route.methods),
        }
        for route in api_router.routes
    ]


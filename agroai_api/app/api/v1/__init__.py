"""API v1 router."""
from fastapi import APIRouter

from app.api.v1 import (
    health,
    recommendations,
    ingestion,
    reports,
    orchestration,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(ingestion.router, tags=["ingestion"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(orchestration.router, tags=["orchestration"])
api_router.include_router(webhooks.router, tags=["webhooks"])

from fastapi import APIRouter

from .demo import router as demo_router   # ⬅️ add this import

api_router = APIRouter()

# keep your existing include_router(...) calls here (health, etc)

api_router.include_router(
    demo_router,
    prefix="/demo",
    tags=["demo"],
)


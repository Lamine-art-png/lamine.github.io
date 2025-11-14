from fastapi import APIRouter

from . import health, demo  # import both sub-routers

# Global /v1 prefix for all v1 endpoints
api_router = APIRouter(prefix="/v1")

# /v1/health, /v1/metrics, etc.
api_router.include_router(health.router, tags=["v1"])

# /v1/demo/recommendation (API-key protected)
api_router.include_router(demo.router, tags=["demo"])


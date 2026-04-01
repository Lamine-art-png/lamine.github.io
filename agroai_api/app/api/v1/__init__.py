from fastapi import APIRouter

from . import health

# Global /v1 prefix for all v1 endpoints
api_router = APIRouter(prefix="/v1")

# /v1/health, /v1/metrics, etc.
api_router.include_router(health.router, tags=["v1"])

# Note: endpoints.demo contains only schemas, no router.
# Demo routes are defined in app.main directly.


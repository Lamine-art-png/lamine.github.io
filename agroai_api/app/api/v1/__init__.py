from fastapi import APIRouter

from . import health

# Global /v1 prefix for all v1 endpoints
api_router = APIRouter(prefix="/v1")

# /v1/health, /v1/metrics, etc.
api_router.include_router(health.router, tags=["v1"])

# The application imports app.api.v1.auth directly from app.main. Attach the
# recovery router to that authoritative auth surface here so recovery stays
# versioned with /v1 and does not create another top-level runtime route.
from . import auth as auth_module  # noqa: E402
from . import recovery_v2 as recovery_module  # noqa: E402

auth_module.router.include_router(recovery_module.router)

# Note: endpoints.demo contains only schemas, no router.
# Demo routes are defined in app.main directly.

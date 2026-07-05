from fastapi import APIRouter

from . import health

# Global /v1 prefix for all v1 endpoints
api_router = APIRouter(prefix="/v1")

# /v1/health, /v1/metrics, etc.
api_router.include_router(health.router, tags=["v1"])

# The application imports these authoritative routers directly from app.main.
# Attach stacked hardening routes before main includes them so compatibility is
# preserved without creating duplicate top-level route registrations.
from . import auth as auth_module  # noqa: E402
from . import recovery_v2 as recovery_module  # noqa: E402

auth_module.router.include_router(recovery_module.router)

from . import brain as brain_module  # noqa: E402
from . import brain_safety as brain_safety_module  # noqa: E402

brain_module.router.include_router(brain_safety_module.router)

# Note: endpoints.demo contains only schemas, no router.
# Demo routes are defined in app.main directly.

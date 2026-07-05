from fastapi import APIRouter

from . import health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router, tags=["v1"])

from . import auth as auth_module  # noqa: E402
from . import recovery_v2 as recovery_module  # noqa: E402

auth_module.router.include_router(recovery_module.router)

from . import brain as brain_module  # noqa: E402
from . import brain_safety as brain_safety_module  # noqa: E402

brain_module.router.include_router(brain_safety_module.router)

from . import connector_hub as connector_module  # noqa: E402
from . import connector_oauth_secure as oauth_module  # noqa: E402
from . import connector_stream_api as stream_module  # noqa: E402

connector_module.router.routes[0:0] = list(oauth_module.router.routes)
connector_module.router.include_router(stream_module.router)

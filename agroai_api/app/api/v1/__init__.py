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
from . import connector_provider_sync as provider_sync_module  # noqa: E402
from . import connector_stream_secure as secure_stream_module  # noqa: E402
from . import connector_launch as launch_module  # noqa: E402
from . import connector_launch_secure as launch_secure_module  # noqa: E402
from . import connector_oauth_completion as oauth_completion_module  # noqa: E402

connector_module.router.routes[0:0] = (
    list(oauth_module.router.routes)
    + list(provider_sync_module.router.routes)
    + list(secure_stream_module.router.routes)
)
launch_module.router.routes[0:0] = (
    list(launch_secure_module.router.routes)
    + list(oauth_completion_module.router.routes)
)

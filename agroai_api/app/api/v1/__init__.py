from fastapi import APIRouter

from . import health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router, tags=["v1"])

from . import auth as auth_module  # noqa: E402
from . import recovery_v2 as recovery_module  # noqa: E402

auth_module.router.include_router(recovery_module.router)

from . import billing as billing_module  # noqa: E402,F401
from app.services.commercial_billing_lifecycle import install_commercial_billing_lifecycle  # noqa: E402

install_commercial_billing_lifecycle()

from . import brain as brain_module  # noqa: E402
from . import brain_safety as brain_safety_module  # noqa: E402

brain_module.router.include_router(brain_safety_module.router)

from . import ai as ai_module  # noqa: E402
from . import connector_hub as connector_module  # noqa: E402
from . import connector_connection_upload_secure as connection_upload_module  # noqa: E402
from . import connector_oauth_secure as oauth_module  # noqa: E402
from . import connector_provider_sync as provider_sync_module  # noqa: E402
from . import connector_stream_secure as secure_stream_module  # noqa: E402
from . import runtime_diagnostics_api as runtime_diagnostics_module  # noqa: E402
from . import connector_launch as launch_module  # noqa: E402
from . import connector_launch_secure as launch_secure_module  # noqa: E402
from . import connector_oauth_completion as oauth_completion_module  # noqa: E402
from . import connectors as connector_compat_module  # noqa: E402
from . import connector_upload_commercial as commercial_upload_module  # noqa: E402
from . import product_shell as product_shell_module  # noqa: E402
from . import monetization_convergence as monetization_module  # noqa: E402
from app.services.commercial_packaging_v2 import (  # noqa: E402
    apply_catalog_packaging,
    install_commercial_packaging_v2,
)

install_commercial_packaging_v2()
apply_catalog_packaging(connector_compat_module.CATALOG)


_HIDDEN_COMPAT_OPERATIONS = {
    ("POST", "/connectors/oauth/start"),
    ("POST", "/evidence/upload"),
    ("GET", "/connectors/data-sources"),
    ("GET", "/connectors/jobs"),
    ("GET", "/connectors/connections/{connection_id}/data"),
    ("POST", "/connectors/connections/{connection_id}/upload"),
}


def _hide_compat_schema_shadows() -> None:
    for route in connector_compat_module.router.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", None) or ())
        if any((method, path) in _HIDDEN_COMPAT_OPERATIONS for method in methods):
            route.include_in_schema = False
    for route in ai_module.router.routes:
        if getattr(route, "path", "") == "/ai/chat" and "POST" in set(getattr(route, "methods", None) or ()):
            route.include_in_schema = False


def _remove_duplicate_product_checkout() -> None:
    """Remove the old direct-Stripe compatibility route before canonical aliasing."""
    product_shell_module.router.routes[:] = [
        route
        for route in product_shell_module.router.routes
        if not (
            getattr(route, "path", "") == "/billing/checkout"
            and "POST" in set(getattr(route, "methods", None) or ())
        )
    ]


def _remove_unmetered_evidence_upload() -> None:
    """Remove the old unmetered file-ingestion route before canonical aliasing."""
    connector_module.router.routes[:] = [
        route
        for route in connector_module.router.routes
        if not (
            getattr(route, "path", "") == "/evidence/upload"
            and "POST" in set(getattr(route, "methods", None) or ())
        )
    ]


_remove_unmetered_evidence_upload()
connector_module.router.routes[0:0] = (
    list(commercial_upload_module.router.routes)
    + list(oauth_module.router.routes)
    + list(provider_sync_module.router.routes)
    + list(secure_stream_module.router.routes)
    + list(connection_upload_module.router.routes)
    + list(runtime_diagnostics_module.router.routes)
)
launch_module.router.routes[0:0] = (
    list(launch_secure_module.router.routes)
    + list(oauth_completion_module.router.routes)
)

_remove_duplicate_product_checkout()
product_shell_module.router.include_router(monetization_module.router)

_hide_compat_schema_shadows()

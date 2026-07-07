from fastapi.routing import APIRoute

from app.api.v1 import connector_hub as connector_module
from app.api.v1 import connectors as connector_compat_module

_TARGET_PATHS = {
    "/evidence/upload",
    "/evidence/upload-stream",
    "/connectors/connections/{connection_id}/upload",
    "/connectors/connections/{connection_id}/upload-stream",
}


def test_every_live_upload_route_is_commercially_metered():
    found = set()
    for router in (connector_module.router, connector_compat_module.router):
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            if route.path not in _TARGET_PATHS or "POST" not in (route.methods or set()):
                continue
            found.add(route.path)
            assert getattr(route, "_agroai_commercial_metered", False), route.path

    assert found == _TARGET_PATHS

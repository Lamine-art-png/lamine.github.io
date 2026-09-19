from __future__ import annotations

import inspect

from app.api.v1 import commercial_intelligence_selfserve as selfserve
from app.api.v1 import router_compat


def test_commercial_browser_access_does_not_require_platform_enrollment() -> None:
    source = inspect.getsource(selfserve.require_commercial_intelligence_browser)
    assert "get_auth_context" in inspect.getsource(selfserve)
    assert "require_developer_control_plane" not in source
    assert "require_approved_organization" in source
    assert '{"owner", "admin"}' in source
    assert "require_organization_acceptance" in source


def test_commercial_browser_routes_replace_legacy_gated_routes() -> None:
    expected = {
        "/platform/developer/wallet",
        "/platform/developer/wallet/sync",
        "/platform/developer/wallet/checkout",
        "/platform/developer/intelligence/bootstrap",
        "/platform/developer/intelligence/run",
    }
    assert router_compat._COMMERCIAL_BROWSER_PATHS == expected
    source = inspect.getsource(router_compat.include_commercial_intelligence)
    assert "commercial_intelligence_router.routes[:]" in source
    assert "commercial_selfserve_router" in source


def test_commercial_access_never_grants_physical_or_provider_writes() -> None:
    payload = inspect.getsource(selfserve.commercial_access)
    assert '"physical_execution": False' in payload
    assert '"provider_writes": False' in payload
    assert '"live_advisory": True' in payload

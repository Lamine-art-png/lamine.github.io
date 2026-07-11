from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RouteSurface:
    method: str
    route: str
    surface: str
    authentication: str
    required_scopes: tuple[str, ...] = ()
    public_openapi: bool = False
    idempotency_required: bool = False
    rate_limit_policy: str = "platform-standard"
    deprecation_status: str = "active"


ROUTE_MANIFEST: tuple[RouteSurface, ...] = (
    RouteSurface("GET", "/v1/platform/health", "public_metadata", "anonymous", public_openapi=True, rate_limit_policy="none"),
    RouteSurface("GET", "/v1/platform/openapi.json", "public_metadata", "anonymous", public_openapi=True, rate_limit_policy="none"),
    RouteSurface("GET", "/v1/platform/route-manifest", "public_metadata", "anonymous", public_openapi=False, rate_limit_policy="none"),
    RouteSurface("GET", "/v1/platform/me", "platform_api_partner", "platform_api_key", ("projects:read",), True),
    RouteSurface("GET", "/v1/platform/providers", "platform_api_partner", "platform_api_key", ("connectors:read",), True),
    RouteSurface("POST", "/v1/platform/providers/{provider_id}/validate-credentials", "platform_api_partner", "platform_api_key", ("connectors:write",), True, True),
    RouteSurface("POST", "/v1/platform/actions/plan", "platform_api_partner", "platform_api_key", ("actions:plan",), True, True),
    RouteSurface("POST", "/v1/platform/actions/execute", "platform_api_partner", "platform_api_key", ("actions:execute",), True, True),
    RouteSurface("GET", "/v1/platform/developer/projects", "enterprise_portal", "portal_jwt", ("projects:read",), False),
    RouteSurface("POST", "/v1/platform/developer/projects", "enterprise_portal", "portal_jwt", ("projects:write",), False, True),
    RouteSurface("POST", "/v1/platform/developer/projects/{project_id}/service-accounts", "enterprise_portal", "portal_jwt", ("service_accounts:write",), False, True),
    RouteSurface("POST", "/v1/platform/developer/service-accounts/{service_account_id}/keys", "enterprise_portal", "portal_jwt", ("keys:write",), False, True),
    RouteSurface("POST", "/v1/platform/developer/keys/{key_id}/revoke", "enterprise_portal", "portal_jwt", ("keys:write",), False, True),
    RouteSurface("POST", "/v1/platform/developer/keys/{key_id}/rotate", "enterprise_portal", "portal_jwt", ("keys:write",), False, True),
    RouteSurface("GET", "/v1/platform/developer/usage", "enterprise_portal", "portal_jwt", ("usage:read",), False),
    RouteSurface("POST", "/v1/platform/developer/webhooks", "enterprise_portal", "portal_jwt", ("webhooks:write",), False, True),
    RouteSurface("GET", "/v1/platform/developer/webhooks", "enterprise_portal", "portal_jwt", ("webhooks:read",), False),
)


def manifest_dicts() -> list[dict]:
    return [asdict(item) for item in ROUTE_MANIFEST]


def public_routes() -> list[dict]:
    return [asdict(item) for item in ROUTE_MANIFEST if item.public_openapi]

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, require_approved_organization
from app.core.config import settings
from app.core.metrics import platform_authentication
from app.core.security import http_bearer
from app.db.base import get_db
from app.models.saas import OrganizationMembership
from app.models.saas import Organization
from app.platform_api.client_ip import client_ip_allowed
from app.platform_api.abuse import record_abuse_signal
from app.platform_api.keys import verify_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.programs import require_active_enrollment, require_api_entitlement
from app.platform_api.request_context import (
    bounded_client_correlation_id,
    new_billing_operation_id,
    new_server_request_id,
)
from app.platform_api.rate_limits import apply_rate_limit_headers, enforce_rate_limit
from app.platform_api.terms import require_organization_acceptance, require_user_acceptance
from app.platform_api.credits import reserve_credits


def _feature_enabled() -> bool:
    return bool(getattr(settings, "PLATFORM_API_ENABLED", False))


def _program_policy_enabled() -> bool:
    return any(
        bool(getattr(settings, name, False))
        for name in (
            "PLATFORM_API_PRIVATE_BETA_ENABLED",
            "PLATFORM_API_PARTNER_PROGRAM_ENABLED",
            "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED",
        )
    )


def require_developer_control_plane(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not bool(getattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    require_approved_organization(ctx.organization)
    if getattr(ctx.membership, "status", "active") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active organization membership required")
    if ctx.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization administrator access required")
    enrollment = require_active_enrollment(db, ctx.organization, operation="developer_control_plane")
    if bool(getattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False)):
        require_user_acceptance(db, organization_id=ctx.organization.id, user_id=ctx.user.id)
    setattr(ctx, "platform_enrollment", enrollment)
    return ctx


def require_platform_api_principal(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> PlatformPrincipal:
    if not _feature_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "platform_api_disabled",
                "type": "configuration_error",
                "message": "The Platform API private beta is not enabled for this environment.",
            },
        )
    request_id = str(getattr(request.state, "request_id", "") or new_server_request_id())
    client_correlation_id = getattr(request.state, "client_correlation_id", None)
    if client_correlation_id is None:
        client_correlation_id = bounded_client_correlation_id(request.headers.get("x-request-id"))
    billing_operation_id = str(
        getattr(request.state, "billing_operation_id", "") or new_billing_operation_id()
    )
    request.state.request_id = request_id
    request.state.client_correlation_id = client_correlation_id
    request.state.billing_operation_id = billing_operation_id
    if not credentials:
        platform_authentication.labels(environment="unknown", outcome="missing_key").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code": "authentication_required",
                "type": "authentication_error",
                "message": "A Platform API key is required.",
                "request_id": request_id,
            },
        )
    verified = verify_platform_key(db, credentials.credentials)
    if verified is None:
        platform_authentication.labels(environment="unknown", outcome="invalid_key").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code": "invalid_api_key",
                "type": "authentication_error",
                "message": "The Platform API key is invalid, expired, revoked, or disabled.",
                "request_id": request_id,
            },
        )
    if not client_ip_allowed(request, list(verified.key.cidr_allowlist_json or [])):
        platform_authentication.labels(environment=verified.key.environment, outcome="cidr_denied").inc()
        record_abuse_signal(
            db,
            signal_type="cidr_violation",
            severity="medium",
            organization_id=verified.key.organization_id,
            api_project_id=verified.key.api_project_id,
            api_key_id=verified.key.id,
            automated_action="challenge",
            evidence={"allowlist_present": bool(verified.key.cidr_allowlist_json)},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={
                "code": "client_ip_not_allowed",
                "type": "authentication_error",
                "message": "The client address could not be safely resolved or is outside this API key's CIDR allowlist.",
                "request_id": request_id,
            },
        )
    if _program_policy_enabled():
        organization = db.get(Organization, verified.key.organization_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
                detail={
                    "code": "invalid_api_key",
                    "type": "authentication_error",
                    "message": "The Platform API key is invalid, expired, revoked, or disabled.",
                    "request_id": request_id,
                },
            )
        try:
            require_api_entitlement(
                db,
                organization,
                environment=verified.key.environment,
                operation="api_key_authentication",
                api_project_id=verified.key.api_project_id,
            )
        except HTTPException as exc:
            platform_authentication.labels(environment=verified.key.environment, outcome="entitlement_denied").inc()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "platform_api_entitlement_inactive",
                    "type": "authorization_error",
                    "message": "The organization is not currently entitled to use this Platform API key.",
                    "request_id": request_id,
                },
            ) from exc
    if bool(getattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False)):
        require_organization_acceptance(db, organization_id=verified.key.organization_id)
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=verified.key.organization_id,
        workspace_id=verified.key.workspace_id,
        api_project_id=verified.key.api_project_id,
        service_account_id=verified.key.service_account_id,
        api_key_id=verified.key.id,
        scopes=frozenset(verified.key.scopes or []),
        environment=verified.key.environment,
        request_id=request_id,
        client_correlation_id=client_correlation_id,
        billing_operation_id=billing_operation_id,
        resource_restrictions=dict(verified.key.resource_restrictions_json or {}),
        provider_restrictions=dict(verified.key.provider_restrictions_json or {}),
        actor_metadata={"key_fingerprint": verified.key.fingerprint, "project_status": verified.project.status},
    )
    matched_route = getattr(request.scope.get("route"), "path", request.url.path)
    decision = enforce_rate_limit(principal, route_id=str(matched_route))
    apply_rate_limit_headers(response, decision)
    request.state.platform_principal = principal
    # Reuse the request-scoped dependency session for safe metadata logging.
    # This also preserves dependency overrides in tests and avoids opening a
    # second session against an unrelated configured database.
    request.state.platform_db = db
    if request.method == "GET":
        list_paths = {
            "/v1/platform/providers",
            "/v1/platform/fields",
            "/v1/platform/sources",
            "/v1/platform/observations",
            "/v1/platform/recommendations",
            "/v1/platform/reports",
            "/v1/platform/jobs",
            "/v1/platform/request-logs",
        }
        operation_id = "list_query" if request.url.path in list_paths or request.url.path.endswith("/sync-jobs") else "basic_read"
        request.state.platform_credit_reservation = reserve_credits(
            db,
            principal=principal,
            operation_id=operation_id,
            logical_operation_id=billing_operation_id,
        )
        request.state.platform_read_metering = True
    platform_authentication.labels(environment=principal.environment or "unknown", outcome="success").inc()
    return principal


def require_platform_portal_principal(ctx: AuthContext = Depends(require_developer_control_plane)) -> PlatformPrincipal:
    return PlatformPrincipal(
        authentication_type="portal_user",
        organization_id=ctx.organization.id if ctx.organization else None,
        user_id=ctx.user.id,
        scopes=frozenset({"projects:read", "projects:write", "keys:read", "keys:write", "service_accounts:read", "service_accounts:write", "webhooks:read", "webhooks:write", "usage:read"}),
        environment=None,
        actor_metadata={"portal_role": ctx.membership.role if ctx.membership else None},
    )


def ensure_org_membership(db: Session, *, organization_id: str, user_id: str) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == user_id)
        .first()
    )

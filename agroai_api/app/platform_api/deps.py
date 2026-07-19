from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, require_approved_organization
from app.core.config import settings
from app.core.security import http_bearer
from app.db.base import get_db
from app.models.saas import OrganizationMembership
from app.platform_api.client_ip import client_ip_allowed
from app.platform_api.keys import verify_platform_key
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.request_context import bounded_request_id


def _feature_enabled() -> bool:
    return bool(getattr(settings, "PLATFORM_API_ENABLED", False))


def require_developer_control_plane(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not bool(getattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    require_approved_organization(ctx.organization)
    if ctx.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization administrator access required")
    return ctx


def require_platform_api_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
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
    request_id = str(getattr(request.state, "request_id", "") or bounded_request_id(x_request_id))
    request.state.request_id = request_id
    if not credentials:
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
    return PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=verified.key.organization_id,
        workspace_id=verified.key.workspace_id,
        api_project_id=verified.key.api_project_id,
        service_account_id=verified.key.service_account_id,
        api_key_id=verified.key.id,
        scopes=frozenset(verified.key.scopes or []),
        environment=verified.key.environment,
        request_id=request_id,
        resource_restrictions=dict(verified.key.resource_restrictions_json or {}),
        provider_restrictions=dict(verified.key.provider_restrictions_json or {}),
        actor_metadata={"key_fingerprint": verified.key.fingerprint, "project_status": verified.project.status},
    )


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

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import http_bearer, verify_token
from app.db.base import get_db
from app.models.saas import Organization, OrganizationMembership, User, Workspace


@dataclass
class AuthContext:
    user: User
    organization: Organization | None = None
    membership: OrganizationMembership | None = None

APPROVED_ORGANIZATION_STATUSES = {"approved", "approved_legacy"}


def require_approved_organization(organization: Organization | None) -> None:
    if organization is None or getattr(organization, "verification_status", None) not in APPROVED_ORGANIZATION_STATUSES:
        current = getattr(organization, "verification_status", None) or "verification_required"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "organization_verification_required",
                "message": "This organization is not approved for live portal access.",
                "verification_status": current,
            },
        )


def _assert_account_access(user: User) -> None:
    if getattr(user, "account_status", "active") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "account_access_restricted",
                "message": "This account is not approved for portal access.",
            },
        )


def _assert_token_organization_access(payload: dict, user: User, db: Session) -> None:
    org_id = payload.get("org_id") or payload.get("tenant_id")
    if not org_id:
        return
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == str(org_id), OrganizationMembership.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session organization is no longer available")
    require_approved_organization(membership.organization)


def _assert_credential_freshness(payload: dict, user: User) -> None:
    changed_at = getattr(user, "credentials_changed_at", None)
    if not changed_at:
        return

    issued_at = payload.get("iat")
    if isinstance(issued_at, (int, float)):
        # JWT iat values are commonly integer seconds. Compare at the same
        # precision so a fresh token minted later in the credential-change
        # second is not falsely rejected, while every earlier second is.
        if int(float(issued_at)) < int(changed_at.timestamp()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
        return

    expires_at = payload.get("exp")
    if not isinstance(expires_at, (int, float)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")

    # Legacy tokens did not carry iat. Their signer uses a fixed configured
    # lifetime, so infer issuance from exp and reject any token issued before
    # the credential change with no grace window.
    token_issued_at = datetime.fromtimestamp(float(expires_at)) - timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    if token_issued_at < changed_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    _assert_credential_freshness(payload, user)
    _assert_account_access(user)
    _assert_token_organization_access(payload, user, db)
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return None
    _assert_credential_freshness(payload, user)
    _assert_account_access(user)
    _assert_token_organization_access(payload, user, db)
    return user


def require_verified_user(user: User) -> None:
    if user.email_verification_status != "verified" or not user.email_verified_at:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_verification_required",
                "message": "Verify your email to activate your AGRO-AI workspace.",
            },
        )


def _activate_server_authorized_access_profile(db: Session, user: User, organization: Organization | None) -> None:
    """Provision explicit internal/demo identities once, entirely server-side.

    Normal customer requests take the fast no-op path. No header, query string,
    JWT claim, or browser value can select an access profile. Organization
    ownership is enforced by the canonical activation service.
    """

    if organization is None:
        return
    from app.services.non_customer_access import (
        FULL_ACCESS_PROFILES,
        access_profile_metadata,
        activate_configured_profile,
        configured_profile_for_user,
    )

    configured = configured_profile_for_user(user)
    if configured not in FULL_ACCESS_PROFILES:
        return
    current = access_profile_metadata(organization)["profile"]
    if current == configured:
        return
    result = activate_configured_profile(db, user=user, org=organization)
    if result is None:
        return
    db.commit()
    db.refresh(organization)


def get_auth_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthContext:
    require_verified_user(user)
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )
    organization = membership.organization if membership else None
    require_approved_organization(organization)
    _activate_server_authorized_access_profile(db, user, organization)
    return AuthContext(user=user, organization=organization, membership=membership)


def platform_admin_emails() -> set[str]:
    """Return the server-only allowlist for global platform administration."""

    raw = str(getattr(settings, "PLATFORM_ADMIN_EMAILS", "") or "")
    return {value.strip().lower() for value in re.split(r"[,;\s]+", raw) if value.strip()}


def is_platform_admin_user(user: User) -> bool:
    """Check global platform access without trusting organization roles or JWT claims."""

    email = str(getattr(user, "email", "") or "").strip().lower()
    verified = bool(
        getattr(user, "email_verification_status", None) == "verified"
        and getattr(user, "email_verified_at", None)
    )
    return bool(email and verified and email in platform_admin_emails())


def require_platform_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Fail closed unless the verified account is explicitly allowlisted server-side."""

    if not is_platform_admin_user(ctx.user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "platform_admin_required",
                "message": "Platform administrator access is required.",
            },
        )
    return ctx


def require_org_membership(org_id: str, user: User, db: Session) -> tuple[Organization, OrganizationMembership]:
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == org_id, OrganizationMembership.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    require_approved_organization(membership.organization)
    return membership.organization, membership


def require_workspace_access(workspace_id: str, user: User, db: Session) -> tuple[Workspace, OrganizationMembership]:
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == workspace.organization_id,
            OrganizationMembership.user_id == user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    require_approved_organization(membership.organization)
    return workspace, membership


async def verify_demo_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    expected = settings.DEMO_API_KEY
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evaluation API key not configured",
        )
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

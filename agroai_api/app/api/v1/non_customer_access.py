"""Internal/demo access profile API.

No endpoint accepts a client-selected paid plan or entitlement map. Self-activation
is possible only when the authenticated email already appears in a server-side
allowlist. Environment provisioning requires a separate secret token.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.saas import Organization
from app.services.demo_environment import provision_demo_environment
from app.services.non_customer_access import (
    CUSTOMER_PROFILE,
    FULL_ACCESS_PROFILES,
    access_profile_metadata,
    activate_configured_profile,
    configured_profile_for_user,
    revoke_non_customer_access,
)

router = APIRouter(prefix="/internal/access", tags=["internal-access"])


class RevokeAccessRequest(BaseModel):
    organization_id: str


def _require_org(ctx: AuthContext) -> Organization:
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization


def _require_provisioning_token(value: str | None) -> None:
    expected = str(getattr(settings, "NON_CUSTOMER_ACCESS_PROVISIONING_TOKEN", "") or "")
    if not expected:
        # Fail closed and avoid advertising a dormant administrative surface.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not value or not secrets.compare_digest(value, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid provisioning token")


def _demo_autoprovision_enabled() -> bool:
    return (
        str(getattr(settings, "APP_ENV", "") or "").strip().lower() == "demo"
        and bool(getattr(settings, "DEMO_AUTO_PROVISION", False))
    )


@router.on_event("startup")
def auto_provision_dedicated_demo_environment() -> None:
    """Fail closed when an explicitly enabled demo runtime cannot seed itself.

    This path can run only in ``APP_ENV=demo`` and is idempotent. Production and
    customer runtimes are therefore unaffected even if demo credentials exist.
    """

    if not _demo_autoprovision_enabled():
        return
    db = SessionLocal()
    try:
        provision_demo_environment(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/status")
def access_profile_status(ctx: AuthContext = Depends(get_auth_context)) -> dict:
    org = _require_org(ctx)
    actual = access_profile_metadata(org)
    configured = configured_profile_for_user(ctx.user)
    return {
        "access_profile": actual["profile"],
        "billing_required": actual["billing_required"],
        "configured_profile": configured if configured in FULL_ACCESS_PROFILES else CUSTOMER_PROFILE,
        "activation_available": configured in FULL_ACCESS_PROFILES,
        "demo_data_policy": actual.get("demo_data_policy"),
    }


@router.post("/activate")
def activate_access_profile(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    """Idempotently activate the profile pre-authorized for this authenticated email."""

    org = _require_org(ctx)
    result = activate_configured_profile(db, user=ctx.user, org=org)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.commit()
    return {
        "status": "active",
        "access_profile": result.profile,
        "billing_required": False,
        "organization_id": result.organization_id,
        "changed": result.changed,
        "override_count": result.override_count,
    }


@router.post("/provision-demo-environment")
def provision_demo(
    x_provisioning_token: str | None = Header(None, alias="X-AGROAI-Provisioning-Token"),
    db: Session = Depends(get_db),
) -> dict:
    """Create/update the full-access and genuine-Free launch demo identities."""

    _require_provisioning_token(x_provisioning_token)
    try:
        results = provision_demo_environment(db)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "demo_environment_not_configured", "message": str(exc)},
        )
    return {
        "status": "ready",
        "identities": [
            {
                "email": item.email,
                "organization_id": item.organization_id,
                "organization_slug": item.organization_slug,
                "access_profile": item.access_profile,
                "created_user": item.created_user,
                "created_organization": item.created_organization,
            }
            for item in results
        ],
    }


@router.post("/revoke")
def revoke_access_profile(
    payload: RevokeAccessRequest,
    x_provisioning_token: str | None = Header(None, alias="X-AGROAI-Provisioning-Token"),
    db: Session = Depends(get_db),
) -> dict:
    _require_provisioning_token(x_provisioning_token)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    changed = revoke_non_customer_access(db, org=org)
    db.commit()
    return {"status": "revoked" if changed else "unchanged", "organization_id": org.id}

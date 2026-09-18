"""Browser self-service commerce for AGRO-AI Intelligence.

The paid advisory product has a deliberately narrower browser entitlement than
legacy Platform API administration. A verified owner/admin of an approved
organization may fund a wallet, create a restricted LIVE advisory key, and run
advisory intelligence without first receiving a broader Platform program
enrollment. Physical/provider-write privileges remain unavailable.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1 import commercial_intelligence as legacy
from app.core.config import settings
from app.core.organization_access import organization_access_allowed
from app.db.base import get_db
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.terms import require_organization_acceptance


router = APIRouter(prefix="/platform/developer", tags=["commercial-intelligence-browser"])


def require_commercial_intelligence_browser(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not bool(getattr(settings, "PLATFORM_API_ENABLED", False)):
        raise HTTPException(status_code=404, detail={"code": "platform_api_disabled"})
    if ctx.organization is None or ctx.membership is None:
        raise HTTPException(status_code=403, detail={"code": "organization_membership_required"})
    if getattr(ctx.membership, "status", "active") != "active":
        raise HTTPException(status_code=403, detail={"code": "active_membership_required"})
    if not organization_access_allowed(ctx.organization):
        raise HTTPException(status_code=403, detail={"code": "organization_not_approved"})
    if str(ctx.membership.role or "").lower() not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "organization_admin_required", "message": "Owner or admin access is required to manage Intelligence API billing and credentials."},
        )
    if bool(getattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False)):
        require_organization_acceptance(db, organization_id=ctx.organization.id)
    return ctx


@router.get("/intelligence/access")
def commercial_access(ctx: AuthContext = Depends(require_commercial_intelligence_browser)) -> dict[str, Any]:
    return {
        "enabled": True,
        "organization_id": ctx.organization.id if ctx.organization else None,
        "role": ctx.membership.role if ctx.membership else None,
        "surface": "paid_advisory_intelligence",
        "live_advisory": True,
        "physical_execution": False,
        "provider_writes": False,
    }


@router.get("/wallet")
def commercial_wallet(
    ctx: AuthContext = Depends(require_commercial_intelligence_browser),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return legacy._wallet_summary(db, ctx.organization.id)


@router.post("/wallet/sync")
def commercial_wallet_sync(
    ctx: AuthContext = Depends(require_commercial_intelligence_browser),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return legacy._wallet_summary(db, ctx.organization.id)


@router.post("/wallet/checkout")
def commercial_wallet_checkout(
    payload: legacy.WalletCheckoutRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ctx: AuthContext = Depends(require_commercial_intelligence_browser),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return legacy.wallet_checkout(payload=payload, idempotency_key=idempotency_key, ctx=ctx, db=db)


@router.post("/intelligence/bootstrap")
def commercial_bootstrap(
    payload: legacy.BootstrapRequest,
    ctx: AuthContext = Depends(require_commercial_intelligence_browser),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return legacy.bootstrap_intelligence_key(payload=payload, ctx=ctx, db=db)


@router.post("/intelligence/run")
async def commercial_browser_run(
    payload: legacy.BrowserIntelligenceRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ctx: AuthContext = Depends(require_commercial_intelligence_browser),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project, _service_account = legacy._default_advisory_project(db, ctx.organization.id, ctx.user.id)
    db.commit()
    principal = PlatformPrincipal(
        authentication_type="portal_user",
        organization_id=ctx.organization.id,
        workspace_id=payload.workspace_id,
        api_project_id=project.id,
        user_id=ctx.user.id,
        scopes=frozenset(legacy.ADVISORY_SCOPES),
        environment="live",
        request_id=str(uuid.uuid4()),
        actor_metadata={"portal_role": ctx.membership.role, "commercial_intelligence": True},
    )
    return await legacy._execute_paid_intelligence(
        payload=payload,
        idempotency_key=idempotency_key,
        principal=principal,
        db=db,
    )

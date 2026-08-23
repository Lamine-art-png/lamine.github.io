from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, is_platform_admin_user
from app.api.v1.auth import (
    _organization_payload,
    _organization_verification_payload,
    _verification_payload,
)
from app.api.v1.saas import _workspace_payload
from app.db.base import get_db
from app.models.saas import Workspace
from app.services.entitlements import serialize_entitlements

router = APIRouter()


@router.get("/bootstrap")
def portal_bootstrap(
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    """Return the minimum authoritative session state required for Portal first paint.

    This replaces the browser's historical /auth/me -> /orgs -> /workspaces
    waterfall with one authenticated request. Platform developer-console state is
    deliberately excluded because it is not required to render the Enterprise
    Portal shell and can hydrate independently.
    """

    started = perf_counter()
    memberships = [
        membership
        for membership in ctx.user.memberships
        if str(getattr(membership, "status", "active") or "active") == "active"
    ]
    organizations = [
        _organization_payload(membership.organization, membership.role)
        for membership in memberships
    ]

    org_ids = [membership.organization_id for membership in memberships]
    db_started = perf_counter()
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.organization_id.in_(org_ids))
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
        .all()
        if org_ids
        else []
    )
    db_ms = (perf_counter() - db_started) * 1000

    current = (
        _organization_payload(ctx.organization, ctx.membership.role)
        if ctx.organization is not None and ctx.membership is not None
        else None
    )
    total_ms = (perf_counter() - started) * 1000
    response.headers["Server-Timing"] = f"portal_bootstrap_db;dur={db_ms:.1f}, portal_bootstrap_total;dur={total_ms:.1f}"
    response.headers["X-AGROAI-Bootstrap-Ms"] = f"{total_ms:.1f}"
    response.headers["Cache-Control"] = "no-store, max-age=0"

    return {
        "user": {
            "id": ctx.user.id,
            "email": ctx.user.email,
            "name": ctx.user.name,
            "is_active": ctx.user.is_active,
            "account_status": ctx.user.account_status,
        },
        "organizations": organizations,
        "current_organization": current,
        "workspaces": [_workspace_payload(workspace) for workspace in workspaces],
        "role": current["role"] if current else None,
        "plan": current["plan"] if current else None,
        "subscription_status": current["subscription_status"] if current else None,
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else {},
        "verification": _verification_payload(ctx.user),
        "organization_verification": _organization_verification_payload(ctx.organization) if ctx.organization else None,
        "platform_admin": is_platform_admin_user(ctx.user),
    }

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import get_db
from app.models.saas import UsageEvent, Workspace
from app.services.entitlements import serialize_entitlements
from app.services.product_plans import plan_by_id, public_plans, service_add_ons, upgrade_options

router = APIRouter(tags=["product-shell"])


class CheckoutRequest(BaseModel):
    plan_id: Literal["free", "professional", "network"]
    billing_period: Literal["monthly", "annual"] = "monthly"


class SupportTicketRequest(BaseModel):
    category: Literal["support", "integration", "issue", "onboarding", "sales"] = "support"
    subject: str = Field(min_length=2, max_length=160)
    message: str = Field(min_length=2, max_length=4000)
    workspace_id: str | None = None


def _require_org(ctx: AuthContext):
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization, ctx.membership


def _first_workspace(db: Session, org_id: str) -> Workspace | None:
    return (
        db.query(Workspace)
        .filter(Workspace.organization_id == org_id)
        .order_by(Workspace.created_at.asc())
        .first()
    )


def _usage_summary(db: Session, org_id: str) -> dict:
    rows = db.query(UsageEvent.event_type, UsageEvent.quantity).filter(UsageEvent.organization_id == org_id).all()
    totals: dict[str, int] = {}
    for event_type, quantity in rows:
        totals[event_type] = totals.get(event_type, 0) + int(quantity or 0)
    return {
        "uploads": totals.get("upload", 0) + totals.get("evidence_upload", 0),
        "ai_runs": totals.get("ai_run", 0) + totals.get("agent_run", 0),
        "reports": totals.get("report", 0) + totals.get("report_export", 0),
        "field_updates": totals.get("field_update", 0),
        "raw": totals,
    }


def _payment_provider_configured() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", None))


def _profile(ctx: AuthContext, db: Session) -> dict:
    org, membership = _require_org(ctx)
    workspace = _first_workspace(db, org.id)
    return {
        "user": {
            "id": ctx.user.id,
            "name": ctx.user.name,
            "email": ctx.user.email,
            "created_at": ctx.user.created_at.isoformat() if ctx.user.created_at else None,
        },
        "workspace": {
            "id": workspace.id if workspace else None,
            "name": workspace.name if workspace else None,
            "mode": workspace.mode if workspace else None,
        },
        "role": membership.role,
        "plan": plan_by_id(org.plan),
        "account_status": org.subscription_status or "inactive",
        "email_verified": False,
        "two_factor_enabled": False,
        "created_at": ctx.user.created_at.isoformat() if ctx.user.created_at else None,
    }


def _security() -> dict:
    return {
        "email_verified": False,
        "two_factor_enabled": False,
        "login_methods": ["password"],
        "active_sessions": [],
        "recommended_security_actions": [
            "Verify your email address",
            "Set up two-factor verification when the provider is configured",
        ],
    }


def _support_options() -> dict:
    return {
        "options": [
            {"id": "help_center", "label": "Help center", "type": "self_service"},
            {"id": "contact_support", "label": "Contact support", "type": "support"},
            {"id": "book_onboarding", "label": "Book onboarding call", "type": "onboarding"},
            {"id": "report_issue", "label": "Report issue", "type": "issue"},
            {"id": "request_integration", "label": "Request integration", "type": "integration"},
            {"id": "network_sales", "label": "Contact sales for Network", "type": "sales"},
        ],
        "message": "Support requests are ready to route when a support provider is configured.",
    }


def _billing_summary(ctx: AuthContext, db: Session) -> dict:
    org, _membership = _require_org(ctx)
    current_plan = plan_by_id(org.plan)
    return {
        "current_plan": current_plan,
        "plan_id": current_plan["id"],
        "billing_status": org.subscription_status,
        "monthly_price": current_plan["public_price_monthly"],
        "annual_price": current_plan["public_price_annual"],
        "usage_summary": _usage_summary(db, org.id),
        "upgrade_options": upgrade_options(org.plan),
        "service_add_ons": service_add_ons(),
        "payment_provider_configured": _payment_provider_configured(),
    }


@router.get("/product/plans")
def get_product_plans() -> dict:
    return {"plans": public_plans(), "service_add_ons": service_add_ons()}


@router.get("/account/profile")
def account_profile(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _profile(ctx, db)


@router.get("/account/security")
def account_security(_ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return _security()


@router.post("/account/email-verification/request")
def request_email_verification(_ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "status": "queued_for_email_provider_setup",
        "message": "Email verification is ready to configure.",
    }


@router.post("/account/two-factor/start")
def start_two_factor(_ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "status": "setup_required",
        "message": "Two-factor verification is ready to configure.",
    }


@router.get("/billing/summary")
def billing_summary(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _billing_summary(ctx, db)


@router.post("/billing/checkout")
def billing_checkout(payload: CheckoutRequest, ctx: AuthContext = Depends(get_auth_context)) -> dict:
    _require_org(ctx)
    selected = plan_by_id(payload.plan_id)
    if selected["id"] == "free":
        return {
            "status": "already_available",
            "message": "The Free plan is available without checkout.",
            "plan": selected,
        }
    if selected["is_custom_pricing"]:
        return {
            "status": "sales_contact_required",
            "message": "Network plans are scoped with the AGRO-AI team before billing starts.",
            "plan": selected,
        }
    if not _payment_provider_configured():
        return {
            "status": "payment_provider_setup_required",
            "message": "Checkout is ready for payment provider configuration.",
            "plan": selected,
            "billing_period": payload.billing_period,
        }
    return {
        "status": "payment_provider_configured",
        "message": "Use the configured billing session endpoint to create checkout.",
        "plan": selected,
        "billing_period": payload.billing_period,
    }


@router.get("/support/options")
def support_options() -> dict:
    return _support_options()


@router.post("/support/ticket")
def support_ticket(payload: SupportTicketRequest, ctx: AuthContext = Depends(get_auth_context)) -> dict:
    org, _membership = _require_org(ctx)
    return {
        "status": "received_for_support_provider_setup",
        "request": {
            "category": payload.category,
            "subject": payload.subject,
            "message": payload.message,
            "workspace_id": payload.workspace_id,
            "organization_id": org.id,
            "user_email": ctx.user.email,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
        "message": "Support routing is ready to configure.",
    }


@router.get("/app/shell")
def app_shell(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    profile = _profile(ctx, db)
    billing = _billing_summary(ctx, db)
    return {
        "user": profile["user"],
        "workspace": profile["workspace"],
        "plan": profile["plan"],
        "nav": [
            {"section": "Operate", "items": ["Command Center", "Field Queue", "Tasks", "Decisions", "Evidence", "Reports", "Connectors"]},
            {"section": "Intelligence", "items": ["Ask AGRO-AI", "Readiness", "Exceptions"]},
            {"section": "Workspace", "items": ["Sources", "Team", "Settings"]},
        ],
        "quick_actions": [
            {"id": "new_field_update", "label": "New field update", "path": "/"},
            {"id": "upload_evidence", "label": "Upload evidence", "path": "/evidence"},
            {"id": "generate_report", "label": "Generate report", "path": "/reports"},
        ],
        "security": _security(),
        "billing": billing,
        "support": _support_options(),
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else {},
    }

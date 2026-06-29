from __future__ import annotations

from datetime import datetime
from typing import Literal

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import get_db
from app.models.saas import (
    Conversation,
    ConversationMessage,
    OnboardingState,
    SaaSRequest,
    TeamInvitation,
    UsageEvent,
    Workspace,
)
from app.services.email_delivery import delivery_status
from app.services.entitlements import (
    assert_can_access_admin_requests,
    assert_can_invite_team,
    get_plan_limits,
    organization_user_count,
    require_owner_or_admin,
    serialize_entitlements,
)
from app.services.product_plans import plan_by_id, public_plans, service_add_ons, upgrade_options

router = APIRouter(tags=["product-shell"])

RequestType = Literal["support", "bug", "integration", "onboarding", "sales", "upgrade", "network_plan", "team_invite"]
RequestStatus = Literal["received", "triaged", "in_progress", "waiting_on_customer", "closed"]
Priority = Literal["low", "medium", "high", "urgent"]
InviteRole = Literal["owner", "admin", "manager", "operator", "viewer"]


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=120)


class CheckoutRequest(BaseModel):
    plan_id: Literal["free", "professional", "team", "network", "enterprise"]
    billing_period: Literal["monthly", "annual"] = "monthly"


class SaaSRequestPayload(BaseModel):
    type: RequestType = "support"
    priority: Priority = "medium"
    name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=240)
    company: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=120)
    subject: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=4000)
    source_page: str | None = Field(default=None, max_length=160)
    workspace_id: str | None = None
    metadata: dict | None = None


class SupportTicketRequest(BaseModel):
    category: Literal["support", "integration", "issue", "onboarding", "sales"] = "support"
    subject: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=4000)
    name: str | None = None
    email: str | None = None
    company: str | None = None
    role: str | None = None
    workspace_id: str | None = None
    source_page: str | None = "support"


class OnboardingStateRequest(BaseModel):
    current_step: str | None = None
    selected_plan: str | None = None
    organization_type: str | None = None
    acres_or_sites: str | None = None
    primary_goal: str | None = None
    completed_steps: list[str] | None = None
    workspace_id: str | None = None


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    workspace_id: str | None = None
    message: str | None = None


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    audience: str | None = None
    output: str | None = None


class AdminRequestUpdate(BaseModel):
    status: RequestStatus | None = None
    priority: Priority | None = None


class TeamInvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    role: InviteRole = "viewer"


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


def _workspace_for(ctx: AuthContext, db: Session, workspace_id: str | None) -> Workspace | None:
    org, _membership = _require_org(ctx)
    if workspace_id:
        workspace = db.get(Workspace, workspace_id)
        if not workspace or workspace.organization_id != org.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return _first_workspace(db, org.id)


def _usage_summary(db: Session, org_id: str) -> dict:
    rows = db.query(UsageEvent.event_type, UsageEvent.quantity).filter(UsageEvent.organization_id == org_id).all()
    totals: dict[str, int] = {}
    for event_type, quantity in rows:
        totals[event_type] = totals.get(event_type, 0) + int(quantity or 0)
    return {
        "uploads": totals.get("upload", 0) + totals.get("evidence_upload", 0),
        "agro_ai_runs": totals.get("ai_run", 0) + totals.get("agent_run", 0),
        "reports": totals.get("report", 0) + totals.get("report_export", 0),
        "field_updates": totals.get("field_update", 0),
    }


def _price_id(plan_id: str, billing_period: str) -> str | None:
    annual = billing_period == "annual"
    matrix = {
        "professional": settings.STRIPE_PRICE_PRO_ANNUAL if annual else (settings.STRIPE_PRICE_PRO_MONTHLY or settings.STRIPE_PRICE_ASSURANCE_MONTHLY or settings.STRIPE_PRICE_PRO or settings.STRIPE_PRICE_WATEROPS_MONTHLY),
        "team": settings.STRIPE_PRICE_TEAM_ANNUAL if annual else settings.STRIPE_PRICE_TEAM_MONTHLY,
        "network": settings.STRIPE_PRICE_NETWORK_ANNUAL if annual else settings.STRIPE_PRICE_NETWORK_MONTHLY,
    }
    return matrix.get(plan_id)


def _technical_billing_ready(plan_id: str, billing_period: str) -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", None) and _price_id(plan_id, billing_period))


def _serialize_request(row: SaaSRequest, *, admin: bool = False) -> dict:
    payload = {
        "id": row.id,
        "type": row.type,
        "status": row.status,
        "priority": row.priority,
        "company": row.company,
        "subject": row.subject,
        "requester": row.email or row.name,
        "source_page": row.source_page,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if admin:
        payload.update(
            {
                "organization_id": row.organization_id,
                "workspace_id": row.workspace_id,
                "user_id": row.user_id,
                "name": row.name,
                "email": row.email,
                "role": row.role,
                "message": row.message,
                "notification_status": row.notification_status,
                "metadata": row.metadata_json or {},
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return payload


def _create_saas_request(
    db: Session,
    *,
    request_type: str,
    subject: str,
    message: str,
    ctx: AuthContext | None = None,
    workspace_id: str | None = None,
    priority: str = "medium",
    name: str | None = None,
    email: str | None = None,
    company: str | None = None,
    role: str | None = None,
    source_page: str | None = None,
    metadata: dict | None = None,
) -> SaaSRequest:
    org = ctx.organization if ctx else None
    user = ctx.user if ctx else None
    row = SaaSRequest(
        organization_id=org.id if org else None,
        workspace_id=workspace_id,
        user_id=user.id if user else None,
        type=request_type,
        status="received",
        priority=priority,
        name=name or (user.name if user else None),
        email=email or (user.email if user else None),
        company=company or (org.name if org else None),
        role=role or (ctx.membership.role if ctx and ctx.membership else None),
        subject=subject,
        message=message,
        source_page=source_page,
        notification_status="stored",
        metadata_json=metadata or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _profile(ctx: AuthContext, db: Session) -> dict:
    org, membership = _require_org(ctx)
    workspace = _first_workspace(db, org.id)
    plan = plan_by_id(org.plan)
    return {
        "user": {
            "id": ctx.user.id,
            "name": ctx.user.name,
            "email": ctx.user.email,
            "created_at": ctx.user.created_at.isoformat() if ctx.user.created_at else None,
        },
        "organization": {"id": org.id, "name": org.name, "status": org.subscription_status},
        "workspace": {
            "id": workspace.id if workspace else None,
            "name": workspace.name if workspace else None,
            "mode": workspace.mode if workspace else None,
        },
        "role": membership.role,
        "plan": plan,
        "account_status": org.subscription_status or "inactive",
        "security": _security_payload(ctx),
        "entitlements": serialize_entitlements(org),
        "created_at": ctx.user.created_at.isoformat() if ctx.user.created_at else None,
    }


def _security_payload(ctx: AuthContext) -> dict:
    verified = bool(ctx.user.email_verified_at and ctx.user.email_verification_status == "verified")
    return {
        "email_verification": {
            "status": "verified" if verified else "unverified",
            "customer_label": "Verified" if verified else "Verification required",
            "action_label": "Verified" if verified else "Resend verification email",
        },
        "two_factor": {
            "status": "not_available_yet",
            "customer_label": "Two-factor setup available on request",
            "action_label": "Request two-factor setup",
        },
        "login_methods": ["password"],
        "active_sessions": [],
        "recommended_security_actions": [
            "Verify your email address" if not verified else "Review active sessions",
            "Request two-factor setup",
        ],
    }


def _support_options() -> dict:
    return {
        "options": [
            {"id": "contact_support", "label": "Contact support", "type": "support"},
            {"id": "report_issue", "label": "Report a problem", "type": "bug"},
            {"id": "request_integration", "label": "Request integration", "type": "integration"},
            {"id": "book_onboarding", "label": "Book onboarding", "type": "onboarding"},
            {"id": "network_sales", "label": "Contact sales", "type": "sales"},
        ],
        "message": "Choose a request type and the AGRO-AI team will follow up.",
    }


def _billing_summary(ctx: AuthContext, db: Session, *, admin: bool = False) -> dict:
    org, _membership = _require_org(ctx)
    current_plan = plan_by_id(org.plan)
    payload = {
        "current_plan": current_plan,
        "plan_id": current_plan["id"],
        "billing_status": org.subscription_status,
        "monthly_price": current_plan["public_price_monthly"],
        "annual_price": current_plan["public_price_annual"],
        "usage_summary": _usage_summary(db, org.id),
        "upgrade_options": upgrade_options(org.plan),
        "service_add_ons": service_add_ons(),
        "annual_savings": "Professional annual billing saves 17%.",
        "invoices": [],
        "entitlements": serialize_entitlements(org),
    }
    if admin:
        payload["billing_setup"] = {
            "stripe_secret_present": bool(getattr(settings, "STRIPE_SECRET_KEY", None)),
            "professional_price_present": bool(_price_id("professional", "monthly")),
        }
    return payload


def _ensure_onboarding(ctx: AuthContext, db: Session) -> OnboardingState:
    org, _membership = _require_org(ctx)
    workspace = _first_workspace(db, org.id)
    state = (
        db.query(OnboardingState)
        .filter(OnboardingState.organization_id == org.id, OnboardingState.user_id == ctx.user.id)
        .first()
    )
    if state:
        return state
    state = OnboardingState(
        organization_id=org.id,
        workspace_id=workspace.id if workspace else None,
        user_id=ctx.user.id,
        current_step="account",
        completed_steps_json=[],
    )
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _serialize_onboarding(state: OnboardingState) -> dict:
    return {
        "id": state.id,
        "organization_id": state.organization_id,
        "workspace_id": state.workspace_id,
        "current_step": state.current_step,
        "selected_plan": state.selected_plan,
        "organization_type": state.organization_type,
        "acres_or_sites": state.acres_or_sites,
        "primary_goal": state.primary_goal,
        "completed_steps": state.completed_steps_json or [],
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


def _classify_intent(content: str) -> tuple[str, list[dict], list[str], list[str]]:
    text = content.lower()
    if any(term in text for term in ["pdf", "report", "owner update", "executive brief"]):
        return (
            "owner_report",
            [
                {"type": "generate_report", "label": "Generate report"},
                {"type": "save_to_reports", "label": "Save to reports"},
                {"type": "download_pdf", "label": "Download PDF"},
            ],
            ["Confirmed evidence scope", "Report audience"],
            ["Choose report type", "Review evidence appendix", "Generate PDF"],
        )
    if any(term in text for term in ["compliance", "packet", "audit"]):
        return (
            "compliance_packet",
            [{"type": "generate_report", "label": "Generate compliance packet"}],
            ["Compliance jurisdiction", "Evidence attachments", "Reviewer requirements"],
            ["Review missing evidence", "Generate compliance packet"],
        )
    if any(term in text for term in ["operator", "checklist", "task", "today"]):
        return (
            "operator_checklist",
            [
                {"type": "create_task", "label": "Create task"},
                {"type": "add_to_command_center", "label": "Add to Command Center"},
                {"type": "generate_operator_checklist", "label": "Generate checklist"},
            ],
            ["Field priority", "Recent updates", "Open exceptions"],
            ["Assign today's highest-risk item", "Collect missing readings", "Confirm field update"],
        )
    if any(term in text for term in ["water", "irrigation", "risk"]):
        return (
            "water_risk_brief",
            [{"type": "add_to_command_center", "label": "Add to Command Center"}],
            ["Recent soil moisture", "Flow or irrigation event", "Weather or ET context"],
            ["Check fields needing attention", "Upload missing water evidence"],
        )
    if any(term in text for term in ["missing", "evidence", "gap"]):
        return (
            "evidence_gap_review",
            [{"type": "create_task", "label": "Create evidence task"}],
            ["Evidence base", "Connected systems", "Report goal"],
            ["Upload first missing file", "Request integration if evidence lives in another system"],
        )
    if any(term in text for term in ["connect", "integration", "wiseconn", "talgil", "openet", "drive", "gmail", "outlook"]):
        return (
            "integration_help",
            [{"type": "request_integration", "label": "Request integration"}],
            ["System name", "Account owner", "Field scope"],
            ["Open Connectors", "Request integration help"],
        )
    if any(term in text for term in ["help", "support", "sales", "onboarding"]):
        return (
            "support_request",
            [{"type": "contact_support", "label": "Contact support"}],
            ["Requester details", "Workspace context"],
            ["Send support request"],
        )
    return (
        "general_answer",
        [{"type": "add_to_command_center", "label": "Add to Command Center"}],
        ["Current workspace evidence"],
        ["Ask about today's priorities", "Upload evidence", "Generate a report"],
    )


def _assistant_answer(content: str, intent: str, missing_data: list[str], actions: list[str]) -> str:
    if intent == "owner_report":
        return "AGRO-AI can prepare an owner-ready update from the workspace evidence. Start by choosing the report type, then review missing evidence before saving or exporting."
    if intent == "compliance_packet":
        return "AGRO-AI can assemble a compliance packet using available evidence and a missing-evidence checklist. The packet should only include records already in this workspace."
    if intent == "operator_checklist":
        return "Here is the operating loop: confirm the highest-risk field, assign the next task, collect missing evidence, then update Command Center when the field action is done."
    if intent == "water_risk_brief":
        return "For a water risk brief, AGRO-AI needs recent moisture, flow or irrigation activity, and weather or ET context. Missing readings should be collected before making a field decision."
    if intent == "evidence_gap_review":
        return "AGRO-AI can review the evidence base and turn gaps into tasks. Start with the evidence required for the next report or review."
    if intent == "integration_help":
        return "AGRO-AI can help connect existing field systems. Create an integration request with the system name, account owner, and field scope so the connection can be planned."
    if intent == "support_request":
        return "AGRO-AI can route this to the right team. Submit a support request with the workspace and desired outcome so it can be tracked in Admin."
    return "AGRO-AI is ready to help operate the workspace. Ask for today's priority, missing evidence, a water risk brief, an operator checklist, or a report draft."


def _serialize_message(row: ConversationMessage) -> dict:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "content": row.content,
        "artifacts": row.artifacts_json or [],
        "citations": row.citations_json or [],
        "missing_data": row.missing_data_json or [],
        "recommended_actions": row.recommended_actions_json or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _conversation_for(ctx: AuthContext, db: Session, conversation_id: str) -> Conversation:
    org, _membership = _require_org(ctx)
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.organization_id != org.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("/product/plans")
def get_product_plans() -> dict:
    return {"plans": public_plans(), "service_add_ons": service_add_ons()}


@router.get("/account/me")
def account_me(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _profile(ctx, db)


@router.get("/account/profile")
def account_profile(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _profile(ctx, db)


@router.patch("/account/profile")
def update_account_profile(payload: ProfileUpdateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    if payload.name is not None:
        ctx.user.name = payload.name.strip() or None
    db.commit()
    return _profile(ctx, db)


@router.get("/account/security")
def account_security(_ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return _security_payload(_ctx)


@router.post("/account/email-verification/request")
def request_email_verification(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(
        db,
        ctx=ctx,
        request_type="support",
        subject="Email verification request",
        message="Customer requested email verification setup.",
        source_page="security",
        metadata={"security_request": "email_verification"},
    )
    return {"status": "received", "message": "Verification request received.", "request_id": row.id}


@router.post("/account/two-factor/start")
def start_two_factor(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(
        db,
        ctx=ctx,
        request_type="support",
        subject="Two-factor setup request",
        message="Customer requested two-factor setup.",
        source_page="security",
        metadata={"security_request": "two_factor"},
    )
    return {"status": "received", "message": "Two-factor setup request received.", "request_id": row.id}


@router.get("/onboarding/state")
def onboarding_state(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return {"onboarding": _serialize_onboarding(_ensure_onboarding(ctx, db))}


@router.post("/onboarding/start")
def onboarding_start(payload: OnboardingStateRequest | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    state = _ensure_onboarding(ctx, db)
    state.current_step = payload.current_step if payload and payload.current_step else "organization"
    db.commit()
    db.refresh(state)
    return {"onboarding": _serialize_onboarding(state)}


@router.patch("/onboarding/state")
def update_onboarding(payload: OnboardingStateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    state = _ensure_onboarding(ctx, db)
    if payload.workspace_id:
        state.workspace_id = _workspace_for(ctx, db, payload.workspace_id).id
    for field in ["current_step", "selected_plan", "organization_type", "acres_or_sites", "primary_goal"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(state, field, value)
    if payload.completed_steps is not None:
        state.completed_steps_json = payload.completed_steps
    db.commit()
    db.refresh(state)
    return {"onboarding": _serialize_onboarding(state)}


@router.post("/onboarding/complete")
def complete_onboarding(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    state = _ensure_onboarding(ctx, db)
    steps = set(state.completed_steps_json or [])
    steps.add("start_operating")
    state.current_step = "complete"
    state.completed_steps_json = sorted(steps)
    db.commit()
    db.refresh(state)
    return {"onboarding": _serialize_onboarding(state), "message": "Your workspace is ready. Start by giving AGRO-AI the evidence it needs to help you operate."}


@router.post("/onboarding/request-help")
def onboarding_help(payload: SaaSRequestPayload, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(db, ctx=ctx, request_type="onboarding", subject=payload.subject, message=payload.message, source_page=payload.source_page or "onboarding", workspace_id=payload.workspace_id)
    return {"status": "received", "message": "Onboarding request received.", "request_id": row.id}


@router.post("/onboarding/request")
def onboarding_request(payload: SupportTicketRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(db, ctx=ctx, request_type="onboarding", subject=payload.subject, message=payload.message, source_page=payload.source_page or "onboarding", workspace_id=payload.workspace_id)
    return {"status": "received", "message": "Onboarding request received.", "request_id": row.id}


@router.get("/billing/summary")
def billing_summary(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _billing_summary(ctx, db)


@router.post("/billing/checkout")
def billing_checkout(payload: CheckoutRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    selected = plan_by_id(payload.plan_id)
    if selected["id"] == "free":
        return {"status": "available", "message": "Free workspace is ready.", "plan": selected}
    if selected["id"] == "enterprise":
        row = _create_saas_request(db, ctx=ctx, request_type="sales", subject="Enterprise pricing request", message="Customer requested Enterprise follow-up.", source_page="billing", metadata={"billing_period": payload.billing_period})
        return {"status": "received", "message": "Sales request received.", "request_id": row.id, "plan": selected}
    if selected["id"] == "network" and not _technical_billing_ready(payload.plan_id, payload.billing_period):
        row = _create_saas_request(db, ctx=ctx, request_type="network_plan", subject="Network plan inquiry", message="Customer requested Network plan follow-up.", source_page="billing", metadata={"billing_period": payload.billing_period})
        return {"status": "received", "message": "Network inquiry received.", "request_id": row.id, "plan": selected}
    if _technical_billing_ready(payload.plan_id, payload.billing_period):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": _price_id(payload.plan_id, payload.billing_period), "quantity": 1}],
                success_url=settings.STRIPE_SUCCESS_URL or f"{settings.APP_URL}/billing?checkout=success",
                cancel_url=settings.STRIPE_CANCEL_URL or f"{settings.APP_URL}/billing?checkout=cancelled",
                client_reference_id=org.id,
                metadata={"organization_id": org.id, "plan": selected["id"], "billing_period": payload.billing_period},
            )
            return {"status": "checkout_ready", "checkout_url": session["url"], "plan": selected}
        except Exception:
            pass
    row = _create_saas_request(db, ctx=ctx, request_type="upgrade", subject=f"{selected['name']} upgrade request", message="Customer requested an upgrade.", source_page="billing", metadata={"plan_id": payload.plan_id, "billing_period": payload.billing_period})
    return {"status": "received", "message": "Upgrade request received.", "request_id": row.id, "plan": selected}


@router.post("/billing/upgrade-request")
def billing_upgrade_request(payload: CheckoutRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(db, ctx=ctx, request_type="upgrade", subject=f"{payload.plan_id.title()} upgrade request", message="Customer requested an upgrade.", source_page="billing", metadata=payload.model_dump())
    return {"status": "received", "message": "Upgrade request received.", "request_id": row.id}


@router.get("/support/options")
def support_options() -> dict:
    return _support_options()


@router.post("/support/ticket")
def support_ticket(payload: SupportTicketRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request_type = "bug" if payload.category == "issue" else payload.category
    row = _create_saas_request(db, ctx=ctx, request_type=request_type, subject=payload.subject, message=payload.message, workspace_id=payload.workspace_id, name=payload.name, email=payload.email, company=payload.company, role=payload.role, source_page=payload.source_page or "support")
    return {"status": "received", "message": "Thanks - your request was received.", "request_id": row.id}


@router.post("/sales/contact")
def sales_contact(payload: SaaSRequestPayload, db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(db, request_type="sales", subject=payload.subject, message=payload.message, priority=payload.priority, name=payload.name, email=payload.email, company=payload.company, role=payload.role, source_page=payload.source_page or "pricing", metadata=payload.metadata)
    return {"status": "received", "message": "Sales request received.", "request_id": row.id}


@router.post("/sales/network-inquiry")
def network_inquiry(payload: SaaSRequestPayload, db: Session = Depends(get_db)) -> dict:
    row = _create_saas_request(db, request_type="network_plan", subject=payload.subject, message=payload.message, priority=payload.priority, name=payload.name, email=payload.email, company=payload.company, role=payload.role, source_page=payload.source_page or "pricing", metadata=payload.metadata)
    return {"status": "received", "message": "Network inquiry received.", "request_id": row.id}


@router.get("/admin/requests")
def admin_requests(type: str | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    assert_can_access_admin_requests(org)
    query = db.query(SaaSRequest).filter(SaaSRequest.organization_id == org.id)
    if type:
        query = query.filter(SaaSRequest.type == type)
    rows = query.order_by(SaaSRequest.created_at.desc()).all()
    return {"requests": [_serialize_request(row, admin=True) for row in rows]}


@router.patch("/admin/requests/{request_id}")
def update_admin_request(request_id: str, payload: AdminRequestUpdate, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    assert_can_access_admin_requests(org)
    row = db.get(SaaSRequest, request_id)
    if not row or row.organization_id != org.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if payload.status is not None:
        row.status = payload.status
    if payload.priority is not None:
        row.priority = payload.priority
    db.commit()
    db.refresh(row)
    return {"request": _serialize_request(row, admin=True)}


@router.get("/admin/system")
def admin_system(ctx: AuthContext = Depends(get_auth_context)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    billing_setup = {
        "configured": bool(settings.STRIPE_SECRET_KEY),
        "needs_setup": not bool(settings.STRIPE_SECRET_KEY and (_price_id("professional", "monthly") or _price_id("team", "monthly") or _price_id("network", "monthly"))),
    }
    email_setup = delivery_status()
    return {
        "api": "Healthy",
        "intelligence": "Healthy",
        "billing": "Configured" if billing_setup["configured"] else "Needs setup",
        "email_delivery": "Configured" if email_setup["configured"] else "Needs setup",
        "frontend_release": getattr(settings, "VERSION", "local"),
        "backend_release": getattr(settings, "VERSION", "local"),
        "last_checked_at": datetime.utcnow().isoformat() + "Z",
        "technical_details": {
            "provider": getattr(settings, "AI_PROVIDER", "") or "offline",
            "model": getattr(settings, "AI_MODEL", "") or "offline",
            "fallback": not bool(getattr(settings, "AI_PROVIDER", "")),
            "env_names": email_setup["missing_env"],
            "api_url": getattr(settings, "API_URL", ""),
            "app_url": getattr(settings, "APP_URL", ""),
            "organization_id": org.id,
            "billing_setup": billing_setup,
        },
    }


def _serialize_invitation(row: TeamInvitation) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "role": row.role,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/team/members")
def team_members(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    members = [
        {
            "id": membership.user.id,
            "name": membership.user.name,
            "email": membership.user.email,
            "role": membership.role,
        }
        for membership in org.memberships
    ]
    return {"members": members, "count": len(members)}


@router.get("/team/invitations")
def list_team_invitations(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    assert_can_invite_team(org)
    rows = db.query(TeamInvitation).filter(TeamInvitation.organization_id == org.id).order_by(TeamInvitation.created_at.desc()).all()
    return {"invitations": [_serialize_invitation(row) for row in rows]}


@router.post("/team/invitations")
def create_team_invitation(payload: TeamInvitationCreateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    assert_can_invite_team(org)
    row = TeamInvitation(
        organization_id=org.id,
        email=payload.email.strip().lower(),
        role=payload.role,
        status="pending",
        invited_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "received", "message": "Invitation created.", "invitation": _serialize_invitation(row)}


@router.delete("/team/invitations/{invitation_id}")
def delete_team_invitation(invitation_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)
    assert_can_invite_team(org)
    row = db.get(TeamInvitation, invitation_id)
    if not row or row.organization_id != org.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    row.status = "revoked"
    db.commit()
    return {"ok": True}


@router.get("/conversations")
def list_conversations(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    rows = db.query(Conversation).filter(Conversation.organization_id == org.id).order_by(Conversation.updated_at.desc()).all()
    return {"conversations": [{"id": row.id, "title": row.title, "status": row.status, "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in rows]}


@router.post("/conversations")
def create_conversation(payload: ConversationCreateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    workspace = _workspace_for(ctx, db, payload.workspace_id)
    title = payload.title or (payload.message[:80] if payload.message else "New AGRO-AI conversation")
    row = Conversation(organization_id=org.id, workspace_id=workspace.id if workspace else None, user_id=ctx.user.id, title=title, status="open")
    db.add(row)
    db.commit()
    db.refresh(row)
    if payload.message:
        _add_conversation_message(row, payload.message, ctx, db)
        db.refresh(row)
    return get_conversation(row.id, ctx, db)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    row = _conversation_for(ctx, db, conversation_id)
    messages = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == row.id).order_by(ConversationMessage.created_at.asc()).all()
    return {
        "conversation": {"id": row.id, "title": row.title, "status": row.status, "workspace_id": row.workspace_id},
        "messages": [_serialize_message(message) for message in messages],
    }


def _add_conversation_message(conversation: Conversation, content: str, ctx: AuthContext, db: Session) -> ConversationMessage:
    user_message = ConversationMessage(conversation_id=conversation.id, organization_id=conversation.organization_id, user_id=ctx.user.id, role="user", content=content)
    db.add(user_message)
    intent, artifact_actions, missing_data, recommended_actions = _classify_intent(content)
    answer = _assistant_answer(content, intent, missing_data, recommended_actions)
    assistant = ConversationMessage(
        conversation_id=conversation.id,
        organization_id=conversation.organization_id,
        user_id=None,
        role="assistant",
        content=answer,
        artifacts_json=[{"intent": intent, "actions": artifact_actions}],
        citations_json=[],
        missing_data_json=missing_data,
        recommended_actions_json=recommended_actions,
    )
    conversation.updated_at = datetime.utcnow()
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    return assistant


@router.post("/conversations/{conversation_id}/messages")
def add_conversation_message(conversation_id: str, payload: ConversationMessageRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    conversation = _conversation_for(ctx, db, conversation_id)
    assistant = _add_conversation_message(conversation, payload.content, ctx, db)
    return {"message": _serialize_message(assistant)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    conversation = _conversation_for(ctx, db, conversation_id)
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@router.get("/app/shell")
def app_shell(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    profile = _profile(ctx, db)
    org, _membership = _require_org(ctx)
    return {
        "user": profile["user"],
        "organization": profile["organization"],
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
            {"id": "agro_ai_chat", "label": "Ask AGRO-AI", "path": "/intelligence"},
            {"id": "generate_report", "label": "Generate report", "path": "/reports"},
        ],
        "security": _security_payload(ctx),
        "billing": _billing_summary(ctx, db),
        "support": _support_options(),
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else {},
        "usage": {
            "members": organization_user_count(db, org),
            **_usage_summary(db, org.id),
        },
    }

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import get_db
from app.models.saas import UsageEvent, Workspace
from app.services.entitlements import serialize_entitlements
from app.services.notification_service import send_notification
from app.services.product_plans import plan_by_id, public_plans, service_add_ons, upgrade_options

router = APIRouter(tags=["product-shell"])

RequestKind = Literal["support", "integration", "bug", "onboarding", "sales", "network_plan"]


class CheckoutRequest(BaseModel):
    plan_id: Literal["free", "professional", "network"]
    billing_period: Literal["monthly", "annual"] = "monthly"


class SupportTicketRequest(BaseModel):
    category: Literal["support", "integration", "issue", "bug", "onboarding", "sales", "network_plan"] = "support"
    subject: str = Field(min_length=2, max_length=160)
    message: str = Field(min_length=2, max_length=4000)
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=160)
    workspace_id: str | None = None
    source_page: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SalesContactRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str = Field(min_length=2, max_length=160)
    role: str | None = Field(default=None, max_length=120)
    organization_type: str | None = Field(default=None, max_length=120)
    acres_or_sites: str | None = Field(default=None, max_length=160)
    main_goal: str | None = Field(default=None, max_length=180)
    message: str = Field(min_length=2, max_length=4000)
    preferred_contact_method: str | None = Field(default=None, max_length=80)


class OnboardingRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=120)
    goal: str = Field(min_length=2, max_length=220)
    message: str | None = Field(default=None, max_length=4000)


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    audience: str | None = Field(default=None, max_length=80)
    output: str | None = Field(default=None, max_length=80)


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


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
        "support_requests": totals.get("support_request", 0) + totals.get("sales_inquiry", 0) + totals.get("onboarding_request", 0),
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
            "Set up two-factor verification when available",
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
        "message": "Choose what you need. AGRO-AI will capture the request in your workspace.",
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


def _request_event_type(kind: str) -> str:
    if kind in {"sales", "network_plan"}:
        return "sales_inquiry"
    if kind == "onboarding":
        return "onboarding_request"
    return "support_request"


def _store_request(
    *,
    db: Session,
    ctx: AuthContext,
    kind: str,
    subject: str,
    message: str,
    workspace_id: str | None = None,
    name: str | None = None,
    email: str | None = None,
    company: str | None = None,
    source_page: str | None = None,
    priority: str = "medium",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    org, _membership = _require_org(ctx)
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    payload = {
        "id": request_id,
        "workspace_id": workspace_id,
        "user_id": ctx.user.id,
        "name": name or ctx.user.name,
        "email": email or ctx.user.email,
        "company": company or org.name,
        "request_type": kind,
        "subject": subject,
        "message": message,
        "priority": priority,
        "status": "received",
        "source_page": source_page or "portal",
        "metadata": metadata or {},
        "created_at": _now(),
    }
    event = UsageEvent(
        organization_id=org.id,
        workspace_id=workspace_id,
        user_id=ctx.user.id,
        event_type=_request_event_type(kind),
        quantity=1,
        metadata_json=payload,
    )
    db.add(event)
    db.commit()
    notification = send_notification(kind=kind, subject=f"AGRO-AI {kind}: {subject}", payload=payload)
    payload["notification_status"] = notification.get("notification_status", "stored_not_notified")
    event.metadata_json = payload
    db.add(event)
    db.commit()
    return payload


def _request_from_event(event: UsageEvent) -> dict[str, Any]:
    payload = dict(event.metadata_json or {})
    payload.setdefault("id", event.id)
    payload.setdefault("created_at", event.created_at.isoformat() if event.created_at else None)
    payload.setdefault("status", "received")
    payload.setdefault("request_type", event.event_type)
    return payload


def _list_requests(db: Session, org_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        db.query(UsageEvent)
        .filter(UsageEvent.organization_id == org_id)
        .filter(UsageEvent.event_type.in_(["support_request", "sales_inquiry", "onboarding_request"]))
        .order_by(UsageEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_request_from_event(row) for row in rows]


def _conversation_events(db: Session, org_id: str, conversation_id: str | None = None) -> list[UsageEvent]:
    query = db.query(UsageEvent).filter(UsageEvent.organization_id == org_id).filter(
        UsageEvent.event_type.in_(["conversation_created", "conversation_message"])
    )
    if conversation_id:
        query = query.filter(UsageEvent.metadata_json["conversation_id"].as_string() == conversation_id)
    return query.order_by(UsageEvent.created_at.asc()).all()


def _message_response(content: str) -> dict[str, Any]:
    lower = content.lower()
    actions = []
    if any(word in lower for word in ["report", "pdf", "brief", "packet"]):
        actions.append({"id": "generate_report", "label": "Generate report", "action": "report_factory"})
    if any(word in lower for word in ["operator", "task", "field", "today"]):
        actions.append({"id": "create_task", "label": "Create operator task", "action": "field_ops"})
    if not actions:
        actions.append({"id": "open_command_center", "label": "Open Command Center", "action": "command_center"})
    return {
        "content": "AGRO-AI received this request. I can turn it into a field task, report, evidence review, or operating checklist from the workspace context.",
        "recommended_actions": actions,
        "missing_data": [],
        "evidence_used": [],
        "artifacts": [],
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
def request_email_verification(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request = _store_request(
        db=db,
        ctx=ctx,
        kind="support",
        subject="Email verification requested",
        message="User requested an account verification email.",
        source_page="security",
        priority="medium",
    )
    return {"status": "received", "request_id": request["id"], "message": "Verification request received."}


@router.post("/account/two-factor/start")
def start_two_factor(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request = _store_request(
        db=db,
        ctx=ctx,
        kind="support",
        subject="Two-factor setup requested",
        message="User requested two-factor verification setup.",
        source_page="security",
        priority="medium",
    )
    return {"status": "received", "request_id": request["id"], "message": "Two-factor setup request received."}


@router.get("/billing/summary")
def billing_summary(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _billing_summary(ctx, db)


@router.post("/billing/checkout")
def billing_checkout(payload: CheckoutRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    _require_org(ctx)
    selected = plan_by_id(payload.plan_id)
    if selected["id"] == "free":
        return {"status": "already_available", "message": "Free is available now.", "plan": selected}
    if selected["is_custom_pricing"]:
        request = _store_request(
            db=db,
            ctx=ctx,
            kind="network_plan",
            subject="Network plan inquiry",
            message="Customer requested Network pricing from billing/pricing.",
            source_page="billing",
            priority="high",
            metadata={"plan_id": payload.plan_id, "billing_period": payload.billing_period},
        )
        return {"status": "request_received", "request_id": request["id"], "message": "Thanks — your Network request was received.", "plan": selected}
    if not _payment_provider_configured():
        request = _store_request(
            db=db,
            ctx=ctx,
            kind="sales",
            subject="Professional upgrade request",
            message="Customer requested a Professional upgrade. Payment provider is not live yet, so route this to AGRO-AI.",
            source_page="billing",
            priority="high",
            metadata={"plan_id": payload.plan_id, "billing_period": payload.billing_period},
        )
        return {"status": "upgrade_request_received", "request_id": request["id"], "message": "Upgrade request received.", "plan": selected}
    return {"status": "payment_provider_configured", "message": "Checkout is ready.", "plan": selected, "billing_period": payload.billing_period}


@router.get("/support/options")
def support_options() -> dict:
    return _support_options()


@router.post("/support/ticket")
def support_ticket(payload: SupportTicketRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request_type = "bug" if payload.category == "issue" else payload.category
    request = _store_request(
        db=db,
        ctx=ctx,
        kind=request_type,
        subject=payload.subject,
        message=payload.message,
        workspace_id=payload.workspace_id,
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        company=payload.company,
        source_page=payload.source_page or "support",
        priority=payload.priority,
        metadata=payload.metadata,
    )
    return {"status": "received", "request_id": request["id"], "request": request, "message": "Thanks — your request was received."}


@router.get("/support/tickets")
def support_tickets(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    return {"status": "ok", "requests": _list_requests(db, org.id)}


@router.post("/sales/contact")
def sales_contact(payload: SalesContactRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request = _store_request(
        db=db,
        ctx=ctx,
        kind="sales",
        subject=f"Sales inquiry from {payload.company}",
        message=payload.message,
        name=payload.name,
        email=str(payload.email),
        company=payload.company,
        source_page="contact_sales",
        priority="high",
        metadata=payload.model_dump(mode="python"),
    )
    return {"status": "received", "request_id": request["id"], "message": "Thanks — your request was received. AGRO-AI will follow up."}


@router.post("/sales/network-inquiry")
def network_inquiry(payload: SalesContactRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request = _store_request(
        db=db,
        ctx=ctx,
        kind="network_plan",
        subject=f"Network inquiry from {payload.company}",
        message=payload.message,
        name=payload.name,
        email=str(payload.email),
        company=payload.company,
        source_page="network_pricing",
        priority="high",
        metadata=payload.model_dump(mode="python"),
    )
    return {"status": "received", "request_id": request["id"], "message": "Thanks — your Network request was received."}


@router.post("/onboarding/request")
def onboarding_request(payload: OnboardingRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    request = _store_request(
        db=db,
        ctx=ctx,
        kind="onboarding",
        subject="Onboarding requested",
        message=payload.message or payload.goal,
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        company=payload.company,
        source_page="onboarding",
        priority="medium",
        metadata=payload.model_dump(mode="python"),
    )
    return {"status": "received", "request_id": request["id"], "message": "Onboarding request received."}


@router.get("/admin/requests")
def admin_requests(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    requests = _list_requests(db, org.id, limit=100)
    return {
        "status": "ok",
        "requests": requests,
        "counts": {
            "support": sum(1 for item in requests if item.get("request_type") in {"support", "bug"}),
            "sales": sum(1 for item in requests if item.get("request_type") in {"sales", "network_plan"}),
            "onboarding": sum(1 for item in requests if item.get("request_type") == "onboarding"),
            "integration": sum(1 for item in requests if item.get("request_type") == "integration"),
        },
    }


@router.get("/conversations")
def conversations(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    created = [event for event in _conversation_events(db, org.id) if event.event_type == "conversation_created"]
    rows = []
    for event in reversed(created):
        metadata = dict(event.metadata_json or {})
        rows.append({
            "id": metadata.get("conversation_id"),
            "title": metadata.get("title") or "AGRO-AI chat",
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "updated_at": metadata.get("updated_at") or (event.created_at.isoformat() if event.created_at else None),
        })
    return {"status": "ok", "conversations": rows}


@router.post("/conversations")
def create_conversation(payload: ConversationCreateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    event = UsageEvent(
        organization_id=org.id,
        user_id=ctx.user.id,
        event_type="conversation_created",
        quantity=1,
        metadata_json={"conversation_id": conversation_id, "title": payload.title or "New AGRO-AI chat", "created_at": _now(), "updated_at": _now()},
    )
    db.add(event)
    db.commit()
    return {"status": "ok", "conversation": {"id": conversation_id, "title": payload.title or "New AGRO-AI chat", "messages": []}}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    events = _conversation_events(db, org.id, conversation_id)
    messages = [dict(event.metadata_json or {}) for event in events if event.event_type == "conversation_message"]
    title = next((dict(event.metadata_json or {}).get("title") for event in events if event.event_type == "conversation_created"), "AGRO-AI chat")
    return {"status": "ok", "conversation": {"id": conversation_id, "title": title, "messages": messages}}


@router.post("/conversations/{conversation_id}/messages")
def add_conversation_message(conversation_id: str, payload: ConversationMessageRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    user_message = {"id": f"msg_{uuid.uuid4().hex[:12]}", "conversation_id": conversation_id, "role": "user", "content": payload.content, "created_at": _now()}
    assistant_body = _message_response(payload.content)
    assistant_message = {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": assistant_body["content"],
        "created_at": _now(),
        "artifacts": assistant_body.get("artifacts", []),
        "citations": [],
        "missing_data": assistant_body.get("missing_data", []),
        "recommended_actions": assistant_body.get("recommended_actions", []),
    }
    db.add(UsageEvent(organization_id=org.id, user_id=ctx.user.id, event_type="conversation_message", quantity=1, metadata_json=user_message))
    db.add(UsageEvent(organization_id=org.id, user_id=ctx.user.id, event_type="conversation_message", quantity=1, metadata_json=assistant_message))
    db.commit()
    return {"status": "ok", "messages": [user_message, assistant_message]}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, _membership = _require_org(ctx)
    events = _conversation_events(db, org.id, conversation_id)
    for event in events:
        event.metadata_json = {**(event.metadata_json or {}), "deleted": True, "deleted_at": _now()}
        db.add(event)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


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
        "recent_requests": _list_requests(db, ctx.organization.id, limit=5) if ctx.organization else [],
        "entitlements": serialize_entitlements(ctx.organization) if ctx.organization else {},
    }

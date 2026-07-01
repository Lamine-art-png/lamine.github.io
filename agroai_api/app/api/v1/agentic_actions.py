"""Agentic action layer for AGRO-AI.

This module turns AGRO-AI from answer-only software into controlled work execution:
- safe digital/manual work can be executed now;
- field/controller/compliance-sensitive actions are converted into approval-gated work;
- everything returns an auditable action envelope.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1.chat_artifacts import ReportEmailRequest, build_report_pdf_bytes
from app.db.base import get_db
from app.models.saas import Workspace
from app.services.email_delivery import delivery_status, send_email
from app.services.field_operating_loop import build_field_ops_context, create_field_update, create_task, field_message

router = APIRouter(prefix="/agentic", tags=["agentic-actions"])

ActionType = Literal[
    "email_report_to_user",
    "create_field_task",
    "record_field_update",
    "parse_field_message",
    "request_controller_action",
    "prepare_operator_outreach",
    "integration_readiness_check",
    "collect_missing_evidence",
]

RiskLevel = Literal["low", "medium", "high", "critical"]
ActionStatus = Literal["ready", "approval_required", "blocked", "executed", "not_executed"]

SAFE_TO_EXECUTE: set[str] = {
    "email_report_to_user",
    "create_field_task",
    "record_field_update",
    "parse_field_message",
    "integration_readiness_check",
    "collect_missing_evidence",
}

APPROVAL_REQUIRED: set[str] = {
    "request_controller_action",
    "prepare_operator_outreach",
}

FIELD_TERMS = ("field", "block", "ranch", "farm", "operator", "grower", "crew", "pump", "valve", "irrigation", "meter")
REPORT_TERMS = ("report", "pdf", "brief", "memo", "packet", "analysis", "document")
EMAIL_TERMS = ("email", "send", "mail", "forward")
TASK_TERMS = ("task", "todo", "assign", "follow up", "check", "verify", "inspect", "collect", "call")
CONTROLLER_TERMS = ("open valve", "close valve", "start irrigation", "stop irrigation", "turn on", "turn off", "controller", "wiseconn", "talgil")
INTEGRATION_TERMS = ("connect", "integration", "sync", "oauth", "wiseconn", "talgil", "john deere", "operations center", "gmail", "drive")


class ActionPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=12000)
    workspace_id: str | None = None
    answer: str | None = None
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    audience: str | None = None


class ActionExecuteRequest(BaseModel):
    action_type: ActionType
    workspace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_confirmed: bool = False


def _require_org(ctx: AuthContext) -> str:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization.id


def _workspace(db: Session, organization_id: str, workspace_id: str | None) -> Workspace | None:
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return query.order_by(Workspace.created_at.asc()).first()


def _field_context(db: Session, ctx: AuthContext, workspace_id: str | None = None):
    organization_id = _require_org(ctx)
    return build_field_ops_context(db, organization_id, _workspace(db, organization_id, workspace_id))


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _slug(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _field_hint(text: str) -> str | None:
    patterns = [
        r"(?:field|block|ranch|farm)\s+([a-zA-Z0-9 _.-]{2,40})",
        r"for\s+([a-zA-Z0-9 _.-]{2,40})\s+(?:field|block|ranch|farm)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,-")[:80]
    return None


def _priority(text: str) -> str:
    if any(term in text for term in ("urgent", "critical", "today", "now", "high priority", "asap", "leak", "failure", "blocked")):
        return "high"
    if any(term in text for term in ("low", "later", "when possible")):
        return "low"
    return "medium"


def _action_card(
    *,
    action_type: ActionType,
    title: str,
    description: str,
    risk_level: RiskLevel,
    status_value: ActionStatus,
    payload: dict[str, Any] | None = None,
    approval_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": _slug("act"),
        "action_type": action_type,
        "title": title,
        "description": description,
        "risk_level": risk_level,
        "status": status_value,
        "approval_required": status_value == "approval_required" or action_type in APPROVAL_REQUIRED,
        "approval_reason": approval_reason,
        "payload": payload or {},
    }


def plan_actions(instruction: str, *, workspace_id: str | None, answer: str | None, uploaded_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = _normalize(instruction)
    actions: list[dict[str, Any]] = []
    wants_report = _has_any(normalized, REPORT_TERMS)
    wants_email = _has_any(normalized, EMAIL_TERMS)
    field_hint = _field_hint(instruction)

    if wants_report and wants_email:
        actions.append(_action_card(
            action_type="email_report_to_user",
            title="Email the generated report",
            description="Generate the AGRO-AI PDF report and email it to the authenticated user's account address.",
            risk_level="low",
            status_value="ready",
            payload={
                "title": "AGRO-AI Operating Report",
                "question": instruction,
                "answer": answer or "AGRO-AI report requested from workspace context.",
                "uploaded_evidence": uploaded_evidence,
                "workspace_id": workspace_id,
            },
        ))

    if _has_any(normalized, TASK_TERMS) or "missing evidence" in normalized or "evidence gap" in normalized:
        actions.append(_action_card(
            action_type="create_field_task",
            title="Create field follow-up task",
            description="Create an auditable task for the operator or manager instead of leaving the work as advice.",
            risk_level="low",
            status_value="ready",
            payload={
                "title": "Follow up on AGRO-AI recommendation",
                "field": field_hint,
                "block": field_hint,
                "priority": _priority(normalized),
                "why": answer or instruction,
                "instructions": [
                    "Review AGRO-AI's recommendation and the evidence used.",
                    "Collect missing field/controller/ET/compliance evidence if needed.",
                    "Mark the task done only after source data is verified.",
                ],
                "evidence_required": ["timestamp", "field/block", "source file or operator note"],
                "created_from": "missing_evidence" if "evidence" in normalized else "manual",
            },
        ))

    if _has_any(normalized, FIELD_TERMS) and any(term in normalized for term in ("record", "log", "note", "observed", "saw", "reported", "field says", "operator says")):
        actions.append(_action_card(
            action_type="parse_field_message",
            title="Turn field message into evidence",
            description="Parse the field/operator message, create an evidence record, and generate follow-up tasks when needed.",
            risk_level="low",
            status_value="ready",
            payload={
                "message": instruction,
                "sender_role": "operator",
                "channel": "portal",
                "field_hint": field_hint,
            },
        ))

    if _has_any(normalized, CONTROLLER_TERMS):
        actions.append(_action_card(
            action_type="request_controller_action",
            title="Prepare controller action request",
            description="Prepare a controller action request for WiseConn/Talgil or field operator review. AGRO-AI will not directly open/close valves without approval and verified integration state.",
            risk_level="critical",
            status_value="approval_required",
            approval_reason="Physical irrigation/control actions can affect crops, water compliance, equipment, and safety. Human approval and live connector verification are required.",
            payload={
                "requested_command": instruction,
                "field": field_hint,
                "block": field_hint,
                "required_checks": ["live connector status", "field/block match", "water budget", "operator approval", "audit log"],
            },
        ))

    if _has_any(normalized, INTEGRATION_TERMS):
        actions.append(_action_card(
            action_type="integration_readiness_check",
            title="Run integration readiness check",
            description="Check what connector/setup evidence is required before AGRO-AI can act on the external system.",
            risk_level="low",
            status_value="ready",
            payload={"system_hint": instruction, "workspace_id": workspace_id},
        ))

    if not actions:
        actions.append(_action_card(
            action_type="collect_missing_evidence",
            title="Create evidence collection plan",
            description="Translate the answer into concrete evidence AGRO-AI needs next.",
            risk_level="low",
            status_value="ready",
            payload={
                "question": instruction,
                "answer": answer,
                "uploaded_evidence_count": len(uploaded_evidence),
                "evidence_required": ["field/block", "timestamp", "source system", "measurement units", "operator confirmation"],
            },
        ))

    return actions[:5]


@router.post("/actions/plan")
def post_action_plan(
    payload: ActionPlanRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org(ctx)
    workspace = _workspace(db, ctx.organization.id, payload.workspace_id) if ctx.organization else None
    actions = plan_actions(
        payload.instruction,
        workspace_id=workspace.id if workspace else payload.workspace_id,
        answer=payload.answer,
        uploaded_evidence=payload.uploaded_evidence,
    )
    return {
        "status": "ok",
        "workspace_id": workspace.id if workspace else payload.workspace_id,
        "agentic_mode": "controlled_execution",
        "principle": "Safe digital work can execute now; field/control actions require approval and auditability.",
        "actions": actions,
    }


@router.post("/actions/execute")
def post_action_execute(
    payload: ActionExecuteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization_id = _require_org(ctx)
    fctx = _field_context(db, ctx, payload.workspace_id)
    action_type = payload.action_type
    data = payload.payload or {}

    if action_type in APPROVAL_REQUIRED and not payload.approval_confirmed:
        return {
            "status": "approval_required",
            "action_type": action_type,
            "risk_level": "critical" if action_type == "request_controller_action" else "high",
            "reason": "This action can affect people, field operations, customer communications, equipment, or compliance. Approval is required before execution.",
            "prepared_payload": data,
        }

    if action_type not in SAFE_TO_EXECUTE and action_type not in APPROVAL_REQUIRED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action type")

    if action_type == "email_report_to_user":
        recipient = (ctx.user.email or "").strip().lower()
        if not recipient or "@" not in recipient:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Authenticated user email is required")
        report = ReportEmailRequest(
            title=data.get("title") or "AGRO-AI Operating Report",
            question=data.get("question") or "AGRO-AI report",
            answer=data.get("answer") or "AGRO-AI report requested from workspace context.",
            uploaded_evidence=data.get("uploaded_evidence") or [],
        )
        pdf = build_report_pdf_bytes(report, organization_id)
        delivery = delivery_status()
        result = send_email(
            to_email=recipient,
            subject=f"{report.title or 'AGRO-AI Operating Report'} — AGRO-AI report",
            text_body="Attached is the AGRO-AI operating report requested from your workspace.",
            html_body="<p>Attached is the AGRO-AI operating report requested from your workspace.</p>",
            attachments=[{"filename": "agroai-operating-report.pdf", "content_type": "application/pdf", "data": pdf}],
        )
        return {"status": "executed" if result.get("ok") else "not_executed", "action_type": action_type, "recipient": recipient, "delivery_configured": delivery.get("configured"), "delivery": result}

    if action_type == "create_field_task":
        task = create_task(
            fctx,
            title=str(data.get("title") or "AGRO-AI field follow-up task")[:180],
            field=data.get("field"),
            block=data.get("block"),
            assigned_to=data.get("assigned_to"),
            priority=data.get("priority") if data.get("priority") in {"high", "medium", "low"} else "medium",
            why=str(data.get("why") or "Created by AGRO-AI action layer")[:1200],
            instructions=[str(item)[:500] for item in data.get("instructions") or []],
            evidence_required=[str(item)[:220] for item in data.get("evidence_required") or []],
            created_from=data.get("created_from") if data.get("created_from") in {"exception", "decision", "missing_evidence", "manual", "field_update"} else "manual",
        )
        return {"status": "executed", "action_type": action_type, "created_task": task}

    if action_type == "record_field_update":
        update = create_field_update(
            fctx,
            field_id=data.get("field_id"),
            field_name=data.get("field_name") or data.get("field"),
            block=data.get("block"),
            crop=data.get("crop"),
            update_text=str(data.get("update_text") or data.get("message") or "AGRO-AI recorded field update")[:5000],
            event_type=data.get("event_type") or "operator_note",
            water_gallons=data.get("water_gallons"),
            flow_gpm=data.get("flow_gpm"),
            duration_minutes=data.get("duration_minutes"),
            attachments=data.get("attachments") or [],
        )
        return {"status": "executed", "action_type": action_type, "field_update": update}

    if action_type == "parse_field_message":
        result = field_message(
            fctx,
            message=str(data.get("message") or "")[:5000],
            sender_role=data.get("sender_role") or "operator",
            channel=data.get("channel") or "portal",
            field_hint=data.get("field_hint"),
        )
        return {"status": "executed", "action_type": action_type, "field_message": result}

    if action_type == "request_controller_action":
        task = create_task(
            fctx,
            title="Review requested controller/irrigation action",
            field=data.get("field"),
            block=data.get("block"),
            assigned_to=data.get("assigned_to"),
            priority="high",
            why=str(data.get("requested_command") or "Controller action requested by AGRO-AI user")[:1200],
            instructions=[
                "Verify live connector status and field/block mapping.",
                "Confirm water budget, crop risk, and compliance constraints.",
                "Approve or reject the physical control action before execution.",
            ],
            evidence_required=["connector status", "field/block match", "operator approval", "audit trail"],
            created_from="manual",
        )
        return {"status": "approval_recorded", "action_type": action_type, "created_approval_task": task, "physical_action_executed": False}

    if action_type == "integration_readiness_check":
        return {
            "status": "executed",
            "action_type": action_type,
            "readiness": {
                "system_hint": data.get("system_hint"),
                "required_before_live_action": ["connector record", "credential/OAuth status", "field mapping", "recent sync", "audit log"],
                "safe_next_step": "Open connector setup, test connection, upload/export evidence, then rerun AGRO-AI.",
            },
        }

    if action_type == "collect_missing_evidence":
        task = create_task(
            fctx,
            title="Collect missing evidence for AGRO-AI decision",
            field=data.get("field"),
            block=data.get("block"),
            assigned_to=data.get("assigned_to"),
            priority="medium",
            why=str(data.get("answer") or data.get("question") or "AGRO-AI needs more evidence before a reliable decision")[:1200],
            instructions=["Collect each required evidence item and upload it to the workspace.", "Re-run AGRO-AI after the evidence is attached."],
            evidence_required=[str(item)[:220] for item in data.get("evidence_required") or ["field/block", "timestamp", "source system", "units"]],
            created_from="missing_evidence",
        )
        return {"status": "executed", "action_type": action_type, "created_task": task}

    return {"status": "not_executed", "action_type": action_type}

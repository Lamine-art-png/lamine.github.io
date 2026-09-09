"""Canonical controlled execution layer for Ask AGRO-AI.

Voice and text share this module. It turns an authenticated request into auditable
workspace work while keeping external communications, physical control, finance,
and compliance-impacting mutations behind explicit human confirmation.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from html import escape
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1.chat_artifacts import ReportEmailRequest, build_report_pdf_bytes
from app.api.v1.saas import _adopt_legacy_operation_records, _clean_workspace_name
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.models.saas import Organization, UsageEvent, Workspace
from app.services.agentic_artifacts import create_workspace_artifact
from app.services.email_delivery import delivery_status, send_email
from app.services.entitlements import assert_can_create_workspace, require_owner_or_admin
from app.services.field_operating_loop import build_field_ops_context, create_field_update, create_task, field_message
from app.services.provider_sync_jobs import SUPPORTED_PROVIDERS, queue_provider_sync
from app.services.agentic_plan_tokens import sign_action_plan, verify_action_plan

router = APIRouter(prefix="/agentic", tags=["agentic-actions"])

ActionType = Literal[
    "create_operation",
    "update_operation",
    "generate_workspace_artifact",
    "draft_email",
    "send_email",
    "email_report_to_user",
    "sync_connected_sources",
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
    "create_operation",
    "update_operation",
    "generate_workspace_artifact",
    "draft_email",
    "email_report_to_user",
    "sync_connected_sources",
    "create_field_task",
    "record_field_update",
    "parse_field_message",
    "prepare_operator_outreach",
    "integration_readiness_check",
    "collect_missing_evidence",
}

APPROVAL_REQUIRED: set[str] = {
    "send_email",
    "request_controller_action",
}

FIELD_TERMS = ("field", "block", "ranch", "farm", "operator", "grower", "crew", "pump", "valve", "irrigation", "meter")
REPORT_TERMS = ("report", "pdf", "brief", "memo", "packet", "analysis", "document", "word", "presentation", "powerpoint", "ppt", "deck", "slides")
EMAIL_TERMS = ("email", "send", "mail", "forward")
CONTROLLER_TERMS = ("open valve", "close valve", "start irrigation", "stop irrigation", "turn on", "turn off", "controller", "wiseconn", "talgil")
INTEGRATION_TERMS = ("connect", "integration", "oauth", "wiseconn", "talgil", "john deere", "operations center", "gmail", "drive", "outlook", "openet")
SYNC_TERMS = ("sync", "refresh data", "refresh the data", "pull data", "pull the data", "fetch data", "fetch the data", "pull latest", "latest data", "update sources")
ARTIFACT_VERBS = ("create", "generate", "build", "make", "prepare", "draft", "produce", "export")
OPERATION_CREATE_PATTERNS = (
    r"\b(?:create|add|build|set\s*up)\s+(?:a\s+)?(?:new\s+)?(?:operation|workspace)\b",
    r"\bnew\s+(?:operation|workspace)\b",
)
OPERATION_UPDATE_PATTERNS = (
    r"\brename\s+(?:this\s+|the\s+|current\s+)?(?:operation|workspace)\b",
    r"\b(?:update|change|edit)\s+(?:this\s+|the\s+|current\s+)?(?:operation|workspace)\b",
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class ActionPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=12000)
    workspace_id: str | None = None
    answer: str | None = None
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    analysis_context: dict[str, Any] = Field(default_factory=dict)


class ActionExecuteRequest(BaseModel):
    action_type: ActionType
    workspace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_confirmed: bool = False
    plan_token: str | None = None


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
    if any(term in text for term in ("low priority", "later", "when possible")):
        return "low"
    return "medium"


def _clean_extracted(value: str | None, limit: int = 120) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\n\r.,;:'\"")
    return cleaned[:limit] or None


def _recent_operation_instruction(history: list[dict[str, Any]] | None) -> str:
    for item in reversed(history or []):
        if str(item.get("role") or "").lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized = _normalize(content)
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in OPERATION_CREATE_PATTERNS):
            if _operation_name(content):
                return content
    return ""


def _operation_name(text: str) -> str | None:
    patterns = [
        r"(?:operation|workspace)\s+(?:called|named)\s+[\"']?([^\"',.;]{2,100})",
        r"(?:create|add|build|set\s*up)\s+(?:a\s+)?(?:new\s+)?(?:operation|workspace)\s+[\"']?([^\"',.;]{2,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = re.split(r"\s+(?:for|with|in|located\s+in|crop\s+is|region\s+is|mode\s+is)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        cleaned = _clean_extracted(value, 120)
        if cleaned and cleaned.lower() not in {"called", "named", "new"}:
            return cleaned
    return None


def _operation_crop(text: str) -> str | None:
    patterns = [
        r"\bcrop\s*(?:is|=|:)?\s*([a-zA-Z][a-zA-Z0-9 &/-]{1,80}?)(?=\s+(?:in|region|located|mode)\b|[,.!?;]|$)",
        r"\bfor\s+([a-zA-Z][a-zA-Z0-9 &/-]{1,80}?)(?=\s+(?:in|region|located|mode)\b|[,.;]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_extracted(match.group(1), 120)
    return None


def _operation_region(text: str) -> str | None:
    patterns = [
        r"\bregion\s*(?:is|=|:)?\s*([a-zA-Z0-9][a-zA-Z0-9 ,._/-]{1,120}?)(?=\s+(?:with|for|crop|mode)\b|[.!?;]|$)",
        r"\blocated\s+in\s+([a-zA-Z0-9][a-zA-Z0-9 ,._/-]{1,120}?)(?=\s+(?:with|for|crop|mode)\b|[.;]|$)",
        r"\bin\s+([a-zA-Z0-9][a-zA-Z0-9 ,._/-]{1,120}?)(?=\s+(?:with|for|crop|mode)\b|[.;]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_extracted(match.group(1), 160)
            if value and "operation" not in value.lower():
                return value
    return None


def _rename_target(text: str) -> str | None:
    match = re.search(r"\brename\s+(?:this\s+|the\s+|current\s+)?(?:operation|workspace)\s+(?:to|as)\s+[\"']?([^\"',.;]{2,120})", text, flags=re.IGNORECASE)
    return _clean_extracted(match.group(1), 120) if match else None


def _artifact_format(text: str) -> str:
    normalized = _normalize(text)
    if any(term in normalized for term in ("powerpoint", "pptx", "ppt", "slide deck", "slides", "presentation", "deck")):
        return "pptx"
    if any(term in normalized for term in ("word document", "docx", "word file", "document")) and "pdf" not in normalized:
        return "docx"
    return "pdf"


def _artifact_title(text: str, fmt: str) -> str:
    quoted = re.search(r"(?:called|titled|title)\s+[\"']([^\"']{2,160})[\"']", text, flags=re.IGNORECASE)
    if quoted:
        return _clean_extracted(quoted.group(1), 180) or "AGRO-AI Workspace Artifact"
    if fmt == "pptx":
        return "AGRO-AI Operating Presentation"
    if fmt == "docx":
        return "AGRO-AI Workspace Document"
    return "AGRO-AI Operating Report"


def _email_address(text: str) -> str | None:
    match = _EMAIL_RE.search(text or "")
    return match.group(0).lower() if match else None


def _email_subject(text: str) -> str:
    match = re.search(r"\bsubject\s*(?:is|:)?\s*[\"']?([^\"'\n]{2,180})", text, flags=re.IGNORECASE)
    return _clean_extracted(match.group(1), 180) if match else "AGRO-AI operating update"


def _explicit_task_intent(normalized: str) -> bool:
    return bool(
        re.search(r"\b(?:create|add|make|assign|open)\s+(?:a\s+)?(?:new\s+)?(?:task|todo|follow[- ]?up)\b", normalized)
        or re.search(r"\b(?:task|todo|follow[- ]?up)\s+(?:to|for)\b", normalized)
    )


def _explicit_artifact_intent(normalized: str) -> bool:
    has_artifact = _has_any(normalized, REPORT_TERMS)
    has_verb = any(re.search(rf"\b{re.escape(verb)}\b", normalized) for verb in ARTIFACT_VERBS)
    return has_artifact and has_verb


def _action_card(
    *,
    action_type: ActionType,
    title: str,
    description: str,
    risk_level: RiskLevel,
    status_value: ActionStatus,
    payload: dict[str, Any] | None = None,
    approval_reason: str | None = None,
    auto_execute: bool = False,
) -> dict[str, Any]:
    approval_required = status_value == "approval_required" or action_type in APPROVAL_REQUIRED
    return {
        "id": _slug("act"),
        "action_type": action_type,
        "title": title,
        "description": description,
        "risk_level": risk_level,
        "status": status_value,
        "approval_required": approval_required,
        "approval_reason": approval_reason,
        "auto_execute": bool(auto_execute and status_value == "ready" and not approval_required),
        "execution_scope": "external_or_physical" if approval_required else "internal_workspace",
        "payload": payload or {},
    }


def plan_actions(
    instruction: str,
    *,
    workspace_id: str | None,
    answer: str | None,
    uploaded_evidence: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    analysis_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = _normalize(instruction)
    actions: list[dict[str, Any]] = []
    field_hint = _field_hint(instruction)

    # Operations / workspaces -------------------------------------------------
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in OPERATION_CREATE_PATTERNS):
        prior_operation_instruction = _recent_operation_instruction(history)
        source_for_missing = prior_operation_instruction if prior_operation_instruction else instruction
        name = _operation_name(instruction) or _operation_name(source_for_missing)
        region = _operation_region(instruction) or _operation_region(source_for_missing)
        crop = _operation_crop(instruction) or _operation_crop(source_for_missing)
        if name:
            actions.append(_action_card(
                action_type="create_operation",
                title=f"Create operation: {name}",
                description="Create the operation inside this organization and make it available in the AEP operation selector.",
                risk_level="low",
                status_value="ready",
                auto_execute=True,
                payload={
                    "name": name,
                    "crop": crop,
                    "region": region,
                    "mode": "live" if re.search(r"\blive\b", normalized) else "evaluation",
                },
            ))
        else:
            actions.append(_action_card(
                action_type="create_operation",
                title="Create a new operation",
                description="AGRO-AI needs the operation name before it can create the workspace.",
                risk_level="low",
                status_value="blocked",
                payload={"missing": ["name"]},
            ))

    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in OPERATION_UPDATE_PATTERNS):
        patch = {
            "name": _rename_target(instruction),
            "crop": _operation_crop(instruction),
            "region": _operation_region(instruction),
        }
        patch = {key: value for key, value in patch.items() if value}
        actions.append(_action_card(
            action_type="update_operation",
            title="Update current operation",
            description="Apply the requested operation fields inside the authenticated workspace.",
            risk_level="low",
            status_value="ready" if patch else "blocked",
            auto_execute=bool(patch),
            payload=patch or {"missing": ["name, crop, or region"]},
        ))

    # Workspace files / artifacts --------------------------------------------
    if _explicit_artifact_intent(normalized):
        fmt = _artifact_format(instruction)
        label = {"pdf": "PDF report", "docx": "Word document", "pptx": "PowerPoint presentation"}[fmt]
        actions.append(_action_card(
            action_type="generate_workspace_artifact",
            title=f"Generate {label}",
            description=f"Create a real {label} from the grounded AGRO-AI answer and attached workspace evidence.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={
                "format": fmt,
                "title": _artifact_title(instruction, fmt),
                "question": instruction,
                "answer": answer or "",
                "uploaded_evidence": uploaded_evidence,
                "analysis_context": analysis_context or {},
            },
        ))

    # Email / communication ---------------------------------------------------
    recipient = _email_address(instruction)
    wants_email = _has_any(normalized, EMAIL_TERMS)
    wants_draft = bool(re.search(r"\b(?:draft|write|prepare|compose)\b", normalized)) and wants_email
    wants_send = bool(re.search(r"\b(?:send|email|forward|mail)\b", normalized)) and not wants_draft

    if wants_draft:
        actions.append(_action_card(
            action_type="draft_email",
            title="Draft email",
            description="Prepare an editable email draft inside the workspace without sending anything.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={
                "to_email": recipient,
                "subject": _email_subject(instruction),
                "body": answer or instruction,
            },
        ))
    elif wants_send and recipient:
        actions.append(_action_card(
            action_type="send_email",
            title=f"Send email to {recipient}",
            description="Send the prepared message externally after visible confirmation.",
            risk_level="high",
            status_value="approval_required",
            approval_reason="External communications leave the AGRO-AI workspace and can create business commitments. Human confirmation is required.",
            payload={
                "to_email": recipient,
                "subject": _email_subject(instruction),
                "body": answer or instruction,
            },
        ))

    wants_report = _has_any(normalized, REPORT_TERMS)
    if wants_report and wants_email and not recipient and re.search(r"\b(?:me|my email|account email)\b", normalized):
        actions.append(_action_card(
            action_type="email_report_to_user",
            title="Email report to my account",
            description="Generate the AGRO-AI PDF report and email it to the authenticated user's own account address.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={
                "title": _artifact_title(instruction, "pdf"),
                "question": instruction,
                "answer": answer or "AGRO-AI report requested from workspace context.",
                "uploaded_evidence": uploaded_evidence,
                "workspace_id": workspace_id,
            },
        ))

    # Connected data ----------------------------------------------------------
    if _has_any(normalized, SYNC_TERMS):
        actions.append(_action_card(
            action_type="sync_connected_sources",
            title="Pull latest connected data",
            description="Queue durable refresh jobs for configured production connectors in this operation.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={"workspace_id": workspace_id},
        ))
    elif _has_any(normalized, INTEGRATION_TERMS) and any(term in normalized for term in ("check", "status", "ready", "readiness", "setup")):
        actions.append(_action_card(
            action_type="integration_readiness_check",
            title="Run integration readiness check",
            description="Check what setup evidence is required before AGRO-AI can rely on or act through the external system.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={"system_hint": instruction, "workspace_id": workspace_id},
        ))

    # Field work --------------------------------------------------------------
    if _explicit_task_intent(normalized):
        actions.append(_action_card(
            action_type="create_field_task",
            title="Create field follow-up task",
            description="Create an auditable task instead of leaving the requested work as advice.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
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
                "created_from": "manual",
            },
        ))

    if _has_any(normalized, FIELD_TERMS) and any(term in normalized for term in ("record", "log", "note", "observed", "saw", "reported", "field says", "operator says")):
        actions.append(_action_card(
            action_type="parse_field_message",
            title="Turn field message into evidence",
            description="Parse the field/operator message, create an evidence record, and generate follow-up work when needed.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={
                "message": instruction,
                "sender_role": "operator",
                "channel": "portal",
                "field_hint": field_hint,
            },
        ))

    if _has_any(normalized, CONTROLLER_TERMS) and any(term in normalized for term in ("open", "close", "start", "stop", "turn on", "turn off", "execute", "apply")):
        actions.append(_action_card(
            action_type="request_controller_action",
            title="Prepare controller action request",
            description="Prepare the irrigation/controller request for review. AGRO-AI will not physically execute it without verified integration state and human confirmation.",
            risk_level="critical",
            status_value="approval_required",
            approval_reason="Physical irrigation/control actions can affect crops, water compliance, equipment, and safety.",
            payload={
                "requested_command": instruction,
                "field": field_hint,
                "block": field_hint,
                "required_checks": ["live connector status", "field/block match", "water budget", "operator approval", "audit log"],
            },
        ))

    if re.search(r"\b(?:collect|gather|request)\s+(?:the\s+)?missing\s+evidence\b", normalized) or "create evidence collection plan" in normalized:
        actions.append(_action_card(
            action_type="collect_missing_evidence",
            title="Create evidence collection plan",
            description="Create concrete follow-up work for the missing evidence AGRO-AI needs next.",
            risk_level="low",
            status_value="ready",
            auto_execute=True,
            payload={
                "question": instruction,
                "answer": answer,
                "uploaded_evidence_count": len(uploaded_evidence),
                "evidence_required": ["field/block", "timestamp", "source system", "measurement units", "operator confirmation"],
            },
        ))

    # A normal question is allowed to remain a question. Do not manufacture
    # busywork simply because an agentic planner was called.
    return actions[:8]


@router.post("/actions/plan")
def post_action_plan(
    payload: ActionPlanRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_org(ctx)
    workspace = _workspace(db, ctx.organization.id, payload.workspace_id) if ctx.organization else None
    resolved_workspace_id = workspace.id if workspace else payload.workspace_id
    actions = plan_actions(
        payload.instruction,
        workspace_id=resolved_workspace_id,
        answer=payload.answer,
        uploaded_evidence=payload.uploaded_evidence,
        history=payload.history,
        analysis_context=payload.analysis_context,
    )
    for action in actions:
        action["plan_token"] = sign_action_plan(
            organization_id=ctx.organization.id,
            user_id=ctx.user.id,
            workspace_id=resolved_workspace_id,
            action=action,
        )
    return {
        "status": "ok",
        "workspace_id": workspace.id if workspace else payload.workspace_id,
        "agentic_mode": "controlled_execution",
        "principle": "Explicit internal digital work can execute immediately; external or physical actions require confirmation and auditability.",
        "actions": actions,
    }


def _created_workspace_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "organization_id": workspace.organization_id,
        "name": workspace.name,
        "crop": workspace.crop,
        "region": workspace.region,
        "mode": workspace.mode,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


@router.post("/actions/execute")
def post_action_execute(
    payload: ActionExecuteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization_id = _require_org(ctx)
    action_type = payload.action_type
    data = payload.payload or {}
    execution_workspace_id = payload.workspace_id

    if payload.plan_token:
        signed = verify_action_plan(
            payload.plan_token,
            organization_id=organization_id,
            user_id=ctx.user.id,
        )
        action_type = str(signed["action_type"])
        data = signed.get("payload") or {}
        execution_workspace_id = signed.get("workspace_id")
        signed_requires_approval = bool(signed.get("approval_required"))
    else:
        signed_requires_approval = action_type in APPROVAL_REQUIRED

    if (action_type in APPROVAL_REQUIRED or signed_requires_approval) and not payload.approval_confirmed:
        return {
            "status": "approval_required",
            "action_type": action_type,
            "risk_level": "critical" if action_type == "request_controller_action" else "high",
            "reason": "This action leaves the workspace or can affect physical operations. Human confirmation is required before execution.",
            "prepared_payload": data,
        }

    if action_type not in SAFE_TO_EXECUTE and action_type not in APPROVAL_REQUIRED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action type")

    if action_type == "create_operation":
        if not ctx.organization or not ctx.membership:
            raise HTTPException(status_code=403, detail="Organization membership required")
        require_owner_or_admin(ctx.membership.role)
        name = _clean_workspace_name(str(data.get("name") or ""))
        mode = str(data.get("mode") or "evaluation").strip().lower()
        if mode not in {"evaluation", "live"}:
            raise HTTPException(status_code=422, detail="mode must be evaluation or live")
        locked_org = db.query(Organization).filter(Organization.id == ctx.organization.id).with_for_update().one()
        assert_can_create_workspace(db, locked_org, mode)
        primary_workspace = (
            db.query(Workspace)
            .filter(Workspace.organization_id == locked_org.id)
            .order_by(Workspace.created_at.asc(), Workspace.id.asc())
            .first()
        )
        legacy_records_adopted = _adopt_legacy_operation_records(db, locked_org.id, primary_workspace.id) if primary_workspace else 0
        workspace = Workspace(
            organization_id=locked_org.id,
            name=name,
            crop=_clean_extracted(str(data.get("crop") or ""), 120),
            region=_clean_extracted(str(data.get("region") or ""), 160),
            mode=mode,
        )
        db.add(workspace)
        db.flush()
        db.add(UsageEvent(
            organization_id=locked_org.id,
            workspace_id=workspace.id,
            user_id=ctx.user.id,
            event_type="workspace_created",
            quantity=1,
            unit="count",
            metadata_json={"source": "ask_agro_ai_agent", "legacy_records_adopted": legacy_records_adopted},
        ))
        db.commit()
        db.refresh(workspace)
        return {"status": "executed", "action_type": action_type, "created_workspace": _created_workspace_payload(workspace)}

    if action_type == "update_operation":
        if not ctx.membership:
            raise HTTPException(status_code=403, detail="Organization membership required")
        require_owner_or_admin(ctx.membership.role)
        workspace = _workspace(db, organization_id, execution_workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        changed: dict[str, Any] = {}
        if data.get("name"):
            workspace.name = _clean_workspace_name(str(data["name"]))
            changed["name"] = workspace.name
        if "crop" in data and data.get("crop"):
            workspace.crop = _clean_extracted(str(data["crop"]), 120)
            changed["crop"] = workspace.crop
        if "region" in data and data.get("region"):
            workspace.region = _clean_extracted(str(data["region"]), 160)
            changed["region"] = workspace.region
        if not changed:
            raise HTTPException(status_code=422, detail="No operation fields were supplied")
        workspace.updated_at = datetime.utcnow()
        db.add(UsageEvent(
            organization_id=organization_id,
            workspace_id=workspace.id,
            user_id=ctx.user.id,
            event_type="workspace_updated",
            quantity=1,
            unit="count",
            metadata_json={"source": "ask_agro_ai_agent", "changed_fields": sorted(changed)},
        ))
        db.commit()
        db.refresh(workspace)
        return {"status": "executed", "action_type": action_type, "updated_workspace": _created_workspace_payload(workspace), "changed": changed}

    if action_type == "generate_workspace_artifact":
        workspace = _workspace(db, organization_id, execution_workspace_id)
        artifact = create_workspace_artifact(
            db,
            tenant_id=organization_id,
            workspace_id=workspace.id if workspace else execution_workspace_id,
            format_name=str(data.get("format") or "pdf"),
            title=str(data.get("title") or "AGRO-AI Workspace Artifact"),
            question=str(data.get("question") or "AGRO-AI artifact request"),
            answer=str(data.get("answer") or ""),
            uploaded_evidence=list(data.get("uploaded_evidence") or []),
            analysis_context=data.get("analysis_context") if isinstance(data.get("analysis_context"), dict) else {},
        )
        return {"status": "executed", "action_type": action_type, "artifact": artifact}

    if action_type in {"draft_email", "prepare_operator_outreach"}:
        draft = {
            "to_email": str(data.get("to_email") or "").strip().lower() or None,
            "subject": str(data.get("subject") or "AGRO-AI operating update")[:200],
            "body": str(data.get("body") or data.get("message") or "")[:20000],
            "sent": False,
        }
        return {"status": "executed", "action_type": action_type, "draft": draft}

    if action_type == "send_email":
        recipient = str(data.get("to_email") or "").strip().lower()
        if not recipient or not _EMAIL_RE.fullmatch(recipient):
            raise HTTPException(status_code=422, detail="A valid recipient email is required")
        subject = str(data.get("subject") or "AGRO-AI operating update")[:200]
        body = str(data.get("body") or "")[:20000]
        if not body.strip():
            raise HTTPException(status_code=422, detail="Email body is required")
        result = send_email(
            to_email=recipient,
            subject=subject,
            text_body=body,
            html_body=f"<p>{escape(body).replace(chr(10), '<br/>')}</p>",
        )
        return {
            "status": "executed" if result.get("ok") else "not_executed",
            "action_type": action_type,
            "recipient": recipient,
            "delivery": result,
        }

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

    if action_type == "sync_connected_sources":
        query = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == organization_id)
        if execution_workspace_id:
            query = query.filter(ConnectorConnection.workspace_id == execution_workspace_id)
        connections = query.order_by(ConnectorConnection.created_at.asc()).all()
        queued: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for connection in connections:
            if connection.provider not in SUPPORTED_PROVIDERS:
                skipped.append({"connection_id": connection.id, "provider": connection.provider, "reason": "no_production_sync_adapter"})
                continue
            if not connection.credentials_ref:
                skipped.append({"connection_id": connection.id, "provider": connection.provider, "reason": "credentials_not_configured"})
                continue
            try:
                job, reused = queue_provider_sync(db, tenant_id=organization_id, connection=connection, commit=False)
                queued.append({"connection_id": connection.id, "provider": connection.provider, "job_id": job.id, "reused": reused})
            except ValueError as exc:
                skipped.append({"connection_id": connection.id, "provider": connection.provider, "reason": str(exc)})
        db.commit()
        terminal = {"completed", "completed_with_warnings", "failed", "dead_letter"}
        job_statuses: dict[str, str] = {}
        wait_requested = bool(data.get("wait_for_completion"))
        if wait_requested and queued:
            deadline = time.monotonic() + min(max(float(data.get("wait_seconds") or 18.0), 1.0), 25.0)
            job_ids = [str(item["job_id"]) for item in queued if item.get("job_id")]
            while time.monotonic() < deadline:
                db.expire_all()
                rows = db.query(IngestionJob).filter(
                    IngestionJob.tenant_id == organization_id,
                    IngestionJob.id.in_(job_ids),
                ).all()
                job_statuses = {str(row.id): str(row.status or "unknown") for row in rows}
                if job_statuses and all(status_value in terminal for status_value in job_statuses.values()):
                    break
                time.sleep(0.45)
        elif queued:
            job_statuses = {str(item["job_id"]): "queued" for item in queued if item.get("job_id")}

        successful = {"completed", "completed_with_warnings"}
        fresh_data_ready = bool(job_statuses) and all(value in successful for value in job_statuses.values())
        still_running = [job_id for job_id, value in job_statuses.items() if value not in terminal]
        failed_jobs = [job_id for job_id, value in job_statuses.items() if value in {"failed", "dead_letter"}]
        if fresh_data_ready:
            message = "Connected-source refresh completed. A new intelligence pass may now use the refreshed workspace records."
        elif still_running:
            message = "Connected-source refresh is still running. AGRO-AI must not describe the current analysis as based on fully refreshed data."
        elif failed_jobs:
            message = "One or more connected-source refresh jobs failed. AGRO-AI must surface the failed refresh before relying on stale records."
        else:
            message = "No refreshable configured connector completed. AGRO-AI should use only the evidence already available in the workspace."

        return {
            "status": "executed",
            "action_type": action_type,
            "sync": {
                "queued": queued,
                "skipped": skipped,
                "job_statuses": job_statuses,
                "fresh_data_ready": fresh_data_ready,
                "still_running": still_running,
                "failed_jobs": failed_jobs,
                "message": message,
            },
        }

    # The remaining actions operate on the field loop and therefore resolve
    # field context only after non-field actions have been handled.
    fctx = _field_context(db, ctx, execution_workspace_id)

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
                "safe_next_step": "Open connector setup, test connection, sync/upload evidence, then rerun AGRO-AI.",
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

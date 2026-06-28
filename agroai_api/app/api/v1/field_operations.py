"""Field operating loop endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.models.saas import Workspace
from app.services.field_operating_loop import (
    audit_trail,
    autopilot_report,
    build_field_ops_context,
    command_center,
    create_field_update,
    create_task,
    field_message,
    list_tasks,
    update_task_status,
)

router = APIRouter(tags=["field-operations"])


class TaskCreateRequest(BaseModel):
    title: str
    field: str | None = None
    block: str | None = None
    assigned_to: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    why: str
    instructions: list[str] = Field(default_factory=list)
    evidence_required: list[str] = Field(default_factory=list)
    source_exception_id: str | None = None
    source_decision_id: str | None = None
    created_from: Literal["exception", "decision", "missing_evidence", "manual", "field_update"] = "manual"
    workspace_id: str | None = None


class TaskStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "blocked", "done", "needs_review"]
    workspace_id: str | None = None


class FieldUpdateRequest(BaseModel):
    field_id: str | None = None
    field_name: str | None = None
    block: str | None = None
    crop: str | None = None
    update_text: str
    event_type: Literal["observation", "meter_reading", "irrigation_event", "issue", "photo_note", "operator_note", "compliance_note"]
    occurred_at: datetime | None = None
    water_gallons: float | None = None
    flow_gpm: float | None = None
    duration_minutes: float | None = None
    attachments: list[dict] | None = None
    workspace_id: str | None = None


class FieldMessageRequest(BaseModel):
    message: str
    sender_role: Literal["operator", "manager", "agency", "advisor"]
    channel: Literal["portal", "email", "sms", "whatsapp", "slack", "teams"]
    field_hint: str | None = None
    workspace_id: str | None = None


class AutopilotReportRequest(BaseModel):
    audience: Literal["operator", "manager", "owner", "agency", "lender", "grower"]
    scope: Literal["today", "weekly", "field", "compliance", "exceptions"]
    field_id: str | None = None
    workspace_id: str | None = None


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


def _context(db: Session, ctx: AuthContext, workspace_id: str | None = None):
    organization_id = _require_org(ctx)
    return build_field_ops_context(db, organization_id, _workspace(db, organization_id, workspace_id))


@router.get("/field-ops/command-center")
def get_command_center(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return command_center(_context(db, ctx, workspace_id))


@router.get("/field-ops/tasks")
def get_tasks(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return {"status": "ok", "tasks": list_tasks(_context(db, ctx, workspace_id))}


@router.post("/field-ops/tasks/create")
def post_task_create(
    payload: TaskCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    task = create_task(
        _context(db, ctx, payload.workspace_id),
        title=payload.title,
        field=payload.field,
        block=payload.block,
        assigned_to=payload.assigned_to,
        priority=payload.priority,
        why=payload.why,
        instructions=payload.instructions,
        evidence_required=payload.evidence_required,
        source_exception_id=payload.source_exception_id,
        source_decision_id=payload.source_decision_id,
        created_from=payload.created_from,
    )
    return {"status": "ok", "task": task}


@router.post("/field-ops/tasks/{task_id}/status")
def post_task_status(
    task_id: str,
    payload: TaskStatusRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    try:
        task = update_task_status(_context(db, ctx, payload.workspace_id), task_id, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    return {"status": "ok", "task": task}


@router.post("/field-ops/field-update")
def post_field_update(
    payload: FieldUpdateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return create_field_update(
        _context(db, ctx, payload.workspace_id),
        field_id=payload.field_id,
        field_name=payload.field_name,
        block=payload.block,
        crop=payload.crop,
        update_text=payload.update_text,
        event_type=payload.event_type,
        occurred_at=payload.occurred_at,
        water_gallons=payload.water_gallons,
        flow_gpm=payload.flow_gpm,
        duration_minutes=payload.duration_minutes,
        attachments=payload.attachments,
    )


@router.post("/field-ops/field-message")
def post_field_message(
    payload: FieldMessageRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return field_message(
        _context(db, ctx, payload.workspace_id),
        message=payload.message,
        sender_role=payload.sender_role,
        channel=payload.channel,
        field_hint=payload.field_hint,
    )


@router.post("/field-ops/autopilot-report")
def post_autopilot_report(
    payload: AutopilotReportRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return autopilot_report(
        _context(db, ctx, payload.workspace_id),
        audience=payload.audience,
        scope=payload.scope,
        field_id=payload.field_id,
    )


@router.get("/field-ops/audit-trail")
def get_audit_trail(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return {"status": "ok", "events": audit_trail(_context(db, ctx, workspace_id))}

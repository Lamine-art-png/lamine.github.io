"""Enterprise Portal control plane for AGRO-AI autonomous operations."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.autonomy_runtime import AutonomyConflict, AutonomyForbidden, AutonomousOperationsRuntime
from app.agents.human_touch import record_human_touch
from app.agents.models import AgentActionProposal, AgentWorkflowOutcome, AgentWorkflowRun
from app.api.deps import AuthContext, get_auth_context
from app.api.v1.agentic_actions import ActionExecuteRequest, execute_commercial_action
from app.db.base import get_db
from app.services.entitlements import require_owner_or_admin

router = APIRouter(prefix="/autonomy", tags=["autonomous-operations"])


class ProcedureIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    domain: str = Field(min_length=1, max_length=80)
    autonomy_level: int = Field(default=2, ge=0, le=5)
    trigger_type: str = Field(default="manual", min_length=1, max_length=80)
    definition: dict[str, Any] = Field(default_factory=dict)


class ProcedureStatusIn(BaseModel):
    workspace_id: str | None = None
    status: Literal["draft", "active", "disabled"]


class PolicyIn(BaseModel):
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    domain: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    rules: dict[str, Any] = Field(default_factory=dict)


class RunIn(BaseModel):
    workspace_id: str | None = None
    procedure_id: str
    idempotency_key: str = Field(min_length=1, max_length=180)
    source_type: str | None = None
    source_id: str | None = None
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionIn(BaseModel):
    workspace_id: str | None = None
    action_type: Literal[
        "create_field_task",
        "request_controller_action",
        "integration_readiness_check",
        "collect_missing_evidence",
    ]
    idempotency_key: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceIn(BaseModel):
    workspace_id: str | None = None


class EvidenceIn(BaseModel):
    workspace_id: str | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompleteIn(BaseModel):
    workspace_id: str | None = None
    status: Literal["succeeded", "failed", "cancelled"]
    summary: str | None = Field(default=None, max_length=4000)
    metrics: dict[str, Any] = Field(default_factory=dict)


def _runtime(ctx: AuthContext, db: Session, workspace_id: str | None) -> AutonomousOperationsRuntime:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    try:
        return AutonomousOperationsRuntime(
            db,
            organization_id=ctx.organization.id,
            workspace_id=workspace_id,
            actor_user_id=ctx.user.id,
        )
    except AutonomyForbidden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AutonomyForbidden as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AutonomyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _require_write_role(ctx: AuthContext) -> None:
    role = str(getattr(ctx.membership, "role", "") or "")
    if role not in {"owner", "admin", "operator"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "write_role_required", "message": "Your role cannot modify autonomous operations."},
        )


def _require_control_role(ctx: AuthContext) -> None:
    role = str(getattr(ctx.membership, "role", "") or "")
    require_owner_or_admin(role)


def _human_touch(
    db: Session,
    ctx: AuthContext,
    *,
    workspace_id: str | None,
    run_id: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    try:
        record_human_touch(
            db,
            organization_id=ctx.organization.id,
            workspace_id=workspace_id,
            run_id=run_id,
            actor_user_id=ctx.user.id,
            reason=reason,
            details=details,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/procedures", status_code=status.HTTP_201_CREATED)
def create_procedure(payload: ProcedureIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_control_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(
        runtime.create_procedure,
        name=payload.name,
        domain=payload.domain,
        autonomy_level=payload.autonomy_level,
        trigger_type=payload.trigger_type,
        definition=payload.definition,
    )


@router.post("/procedures/{procedure_id}/status")
def set_procedure_status(procedure_id: str, payload: ProcedureStatusIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_control_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.set_procedure_status, procedure_id, payload.status)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_control_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.create_policy, name=payload.name, domain=payload.domain, rules=payload.rules, enabled=payload.enabled)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def start_run(payload: RunIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    existing = None
    if ctx.organization:
        existing = (
            db.query(AgentWorkflowRun)
            .filter(
                AgentWorkflowRun.organization_id == ctx.organization.id,
                AgentWorkflowRun.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
    snapshot = _call(
        runtime.start_run,
        procedure_id=payload.procedure_id,
        idempotency_key=payload.idempotency_key,
        source_type=payload.source_type,
        source_id=payload.source_id,
        payload=payload.payload,
        priority=payload.priority,
    )
    # A run started interactively in the Portal is human-assisted even when the
    # caller labels its source as a field event. Zero-touch runs are created by
    # trusted server-side triggers, which call the runtime directly.
    if existing is None:
        _human_touch(
            db,
            ctx,
            workspace_id=runtime.workspace_id,
            run_id=snapshot["run"]["id"],
            reason="portal_run_start",
        )
        snapshot = _call(runtime.run, snapshot["run"]["id"])
    return snapshot


@router.get("/runs/{run_id}")
def get_run(run_id: str, workspace_id: str | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, workspace_id)
    return _call(runtime.run, run_id)


@router.post("/runs/{run_id}/actions", status_code=status.HTTP_201_CREATED)
def plan_action(run_id: str, payload: ActionIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    existing = (
        db.query(AgentActionProposal)
        .filter(AgentActionProposal.run_id == run_id, AgentActionProposal.idempotency_key == payload.idempotency_key)
        .first()
    )
    action = _call(
        runtime.plan_action,
        run_id,
        action_type=payload.action_type,
        idempotency_key=payload.idempotency_key,
        title=payload.title,
        description=payload.description,
        risk_level=payload.risk_level,
        payload=payload.payload,
    )
    if existing is None:
        _human_touch(
            db,
            ctx,
            workspace_id=runtime.workspace_id,
            run_id=run_id,
            reason="portal_action_plan",
            details={"action_id": action["id"], "action_type": payload.action_type},
        )
    return action


@router.post("/runs/{run_id}/actions/{action_id}/approve")
def approve_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_control_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    # Runtime approval itself increments the cumulative human-touch counter.
    return _call(runtime.decide_action, run_id, action_id, approved=True)


@router.post("/runs/{run_id}/actions/{action_id}/reject")
def reject_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_control_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.decide_action, run_id, action_id, approved=False)


@router.post("/runs/{run_id}/actions/{action_id}/execute")
def execute_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Execute through the existing commercial and production-safety controls."""
    _require_write_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    snapshot = _call(runtime.run, run_id)
    action = next((row for row in snapshot["actions"] if row["id"] == action_id), None)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    if action["status"] != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action is not ready to execute")
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")

    effective_workspace_id = snapshot["run"].get("workspace_id")
    action_type = str(action.get("action_type") or "")
    _human_touch(
        db,
        ctx,
        workspace_id=effective_workspace_id,
        run_id=run_id,
        reason="portal_action_execute",
        details={"action_id": action_id, "action_type": action_type},
    )
    action_payload = action.get("payload") or {}
    nested = {**(action_payload.get("payload") or {}), "request_id": f"autonomy-action:{action_id}"}
    request = ActionExecuteRequest(
        action_type=action_type,
        workspace_id=effective_workspace_id,
        payload=nested,
        approval_confirmed=True,
    )
    try:
        result = execute_commercial_action(
            request,
            ctx=ctx,
            db=db,
            request_id=f"autonomy-action:{action_id}",
            metadata={"autonomy_run_id": run_id, "autonomy_action_id": action_id},
            before_execute=lambda: _call(runtime.begin_action, run_id, action_id),
        )
        executed = result.get("status") in {"executed", "approval_recorded"}
        return _call(runtime.record_action_result, run_id, action_id, succeeded=executed, result=result)
    except Exception:
        db.rollback()
        runtime = _runtime(ctx, db, effective_workspace_id)
        current = _call(runtime.run, run_id)
        current_action = next((row for row in current["actions"] if row["id"] == action_id), None)
        if current_action and current_action.get("execution_status") == "executing":
            _call(runtime.record_action_result, run_id, action_id, succeeded=False, result={"error": "executor_failed"})
        raise


@router.post("/runs/{run_id}/actions/{action_id}/verify")
def verify_action(run_id: str, action_id: str, payload: EvidenceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    _human_touch(
        db,
        ctx,
        workspace_id=runtime.workspace_id,
        run_id=run_id,
        reason="portal_action_verify",
        details={"action_id": action_id},
    )
    return _call(runtime.verify_action, run_id, action_id, evidence_ids=payload.evidence_ids, metadata=payload.metadata)


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: str, payload: CompleteIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write_role(ctx)
    runtime = _runtime(ctx, db, payload.workspace_id)
    existing_outcome = db.query(AgentWorkflowOutcome).filter(AgentWorkflowOutcome.run_id == run_id).first()
    if existing_outcome is None:
        _human_touch(
            db,
            ctx,
            workspace_id=runtime.workspace_id,
            run_id=run_id,
            reason="portal_run_complete",
            details={"status": payload.status},
        )
    return _call(runtime.complete_run, run_id, status_value=payload.status, summary=payload.summary, metrics=payload.metrics)


@router.get("/command-center")
def command_center(workspace_id: str | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, workspace_id)
    return runtime.command_center()

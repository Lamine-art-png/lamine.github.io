"""Enterprise Portal control plane for AGRO-AI autonomous operations."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.autonomy_runtime import AutonomyConflict, AutonomyForbidden, AutonomousOperationsRuntime
from app.api.deps import AuthContext, get_auth_context
from app.api.v1.agentic_actions import ActionExecuteRequest, post_action_execute
from app.db.base import get_db

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
    action_type: str = Field(min_length=1, max_length=100)
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


@router.post("/procedures", status_code=status.HTTP_201_CREATED)
def create_procedure(payload: ProcedureIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
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
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.set_procedure_status, procedure_id, payload.status)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.create_policy, name=payload.name, domain=payload.domain, rules=payload.rules, enabled=payload.enabled)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def start_run(payload: RunIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(
        runtime.start_run,
        procedure_id=payload.procedure_id,
        idempotency_key=payload.idempotency_key,
        source_type=payload.source_type,
        source_id=payload.source_id,
        payload=payload.payload,
        priority=payload.priority,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str, workspace_id: str | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, workspace_id)
    return _call(runtime.run, run_id)


@router.post("/runs/{run_id}/actions", status_code=status.HTTP_201_CREATED)
def plan_action(run_id: str, payload: ActionIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(
        runtime.plan_action,
        run_id,
        action_type=payload.action_type,
        idempotency_key=payload.idempotency_key,
        title=payload.title,
        description=payload.description,
        risk_level=payload.risk_level,
        payload=payload.payload,
    )


@router.post("/runs/{run_id}/actions/{action_id}/approve")
def approve_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.decide_action, run_id, action_id, approved=True)


@router.post("/runs/{run_id}/actions/{action_id}/reject")
def reject_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.decide_action, run_id, action_id, approved=False)


@router.post("/runs/{run_id}/actions/{action_id}/execute")
def execute_action(run_id: str, action_id: str, payload: WorkspaceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Execute through the existing production-safe action adapter and ledger the result."""
    runtime = _runtime(ctx, db, payload.workspace_id)
    snapshot = _call(runtime.run, run_id)
    action = next((row for row in snapshot["actions"] if row["id"] == action_id), None)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    if action["status"] != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action is not ready to execute")

    _call(runtime.begin_action, run_id, action_id)
    action_payload = action.get("payload") or {}
    nested = action_payload.get("payload") or {}
    try:
        result = post_action_execute(
            ActionExecuteRequest(
                action_type=action.get("action_type"),
                workspace_id=payload.workspace_id,
                payload=nested,
                approval_confirmed=True,
            ),
            ctx=ctx,
            db=db,
        )
    except Exception:
        db.rollback()
        runtime = _runtime(ctx, db, payload.workspace_id)
        _call(runtime.record_action_result, run_id, action_id, succeeded=False, result={"error": "executor_failed"})
        raise

    executed = result.get("status") in {"executed", "approval_recorded"}
    return _call(runtime.record_action_result, run_id, action_id, succeeded=executed, result=result)


@router.post("/runs/{run_id}/actions/{action_id}/verify")
def verify_action(run_id: str, action_id: str, payload: EvidenceIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.verify_action, run_id, action_id, evidence_ids=payload.evidence_ids, metadata=payload.metadata)


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: str, payload: CompleteIn, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, payload.workspace_id)
    return _call(runtime.complete_run, run_id, status_value=payload.status, summary=payload.summary, metrics=payload.metrics)


@router.get("/command-center")
def command_center(workspace_id: str | None = None, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime = _runtime(ctx, db, workspace_id)
    return runtime.command_center()

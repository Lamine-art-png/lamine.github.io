"""Authenticated Portal API for AGRO-AI autonomous operations."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.autonomy_runtime import (
    ACTION_CLASSES,
    RISK_LEVELS,
    STEP_TYPES,
    approve_step,
    autonomy_summary,
    create_custom_procedure,
    get_run,
    list_procedures,
    list_runs,
    reject_step,
    start_run,
    complete_step,
    upsert_policy,
)

router = APIRouter(prefix="/autonomy", tags=["autonomous-operations"])
_OPERATION_ROLES = {"owner", "admin", "manager", "operator"}
_POLICY_ROLES = {"owner", "admin", "manager"}


class ProcedureStepIn(BaseModel):
    key: str | None = None
    name: str
    type: Literal["checkpoint", "task_dispatch", "external_action", "verification", "close"]
    action_class: str = "intelligence"
    action_type: str | None = None
    risk: Literal["low", "medium", "high", "critical"] = "low"
    minimum_autonomy_level: Literal["A0", "A1", "A2", "A3", "A4", "A5"] = "A4"
    approval_required: bool = False
    template: dict[str, Any] = Field(default_factory=dict)


class ProcedureCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    domain: str = Field(min_length=2, max_length=80)
    description: str | None = None
    procedure_key: str | None = None
    trigger_types: list[str] = Field(default_factory=lambda: ["manual"])
    steps: list[ProcedureStepIn]
    outcome_contract: dict[str, Any] = Field(default_factory=lambda: {"verified_outcome_required": True})


class RunCreateIn(BaseModel):
    procedure_key: str
    workspace_id: str | None = None
    trigger_type: str = "manual"
    trigger_ref: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    requested_autonomy_level: Literal["A0", "A1", "A2", "A3", "A4", "A5"] | None = None


class StepDecisionIn(BaseModel):
    reason: str | None = None


class StepCompleteIn(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class PolicyIn(BaseModel):
    workspace_id: str | None = None
    autonomy_level: Literal["A0", "A1", "A2", "A3", "A4", "A5"] = "A4"
    action_class_caps: dict[str, Literal["A0", "A1", "A2", "A3", "A4", "A5"]] | None = None
    risk_caps: dict[str, Literal["A0", "A1", "A2", "A3", "A4", "A5"]] | None = None
    constraints: dict[str, Any] | None = None


def _organization_id(ctx: AuthContext) -> str:
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return str(ctx.organization.id)


def _require_role(ctx: AuthContext, allowed: set[str]) -> None:
    role = str(getattr(ctx.membership, "role", "") or "").casefold()
    if role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "autonomy_role_required", "message": "Your organization role cannot perform this autonomous-operations action."},
        )


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Autonomy resource not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Autonomy runtime error")


@router.get("/summary")
def summary(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return autonomy_summary(db, _organization_id(ctx), workspace_id)
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.get("/procedures")
def procedures(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"procedures": list_procedures(db, _organization_id(ctx))}


@router.post("/procedures", status_code=201)
def create_procedure(
    payload: ProcedureCreateIn,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _POLICY_ROLES)
    try:
        return create_custom_procedure(
            db,
            _organization_id(ctx),
            name=payload.name,
            domain=payload.domain,
            description=payload.description,
            procedure_key=payload.procedure_key,
            trigger_types=payload.trigger_types,
            steps=[item.model_dump() for item in payload.steps],
            outcome_contract=payload.outcome_contract,
            actor_user_id=str(ctx.user.id),
        )
    except ValueError as exc:
        raise _handle(exc) from exc


@router.get("/runs")
def runs(
    workspace_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"runs": list_runs(db, _organization_id(ctx), workspace_id=workspace_id, limit=limit)}


@router.post("/runs", status_code=201)
def create_run(
    payload: RunCreateIn,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _OPERATION_ROLES)
    try:
        return start_run(
            db,
            _organization_id(ctx),
            procedure_key=payload.procedure_key,
            workspace_id=payload.workspace_id,
            trigger_type=payload.trigger_type,
            trigger_ref=payload.trigger_ref,
            context=payload.context,
            requested_autonomy_level=payload.requested_autonomy_level,
            actor=str(ctx.user.id),
        )
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.get("/runs/{run_id}")
def run_detail(
    run_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return get_run(db, _organization_id(ctx), run_id)
    except KeyError as exc:
        raise _handle(exc) from exc


@router.post("/runs/{run_id}/steps/{step_id}/approve")
def approve(
    run_id: str,
    step_id: str,
    payload: StepDecisionIn | None = None,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _OPERATION_ROLES)
    try:
        return approve_step(db, _organization_id(ctx), run_id, step_id, actor_user_id=str(ctx.user.id))
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.post("/runs/{run_id}/steps/{step_id}/reject")
def reject(
    run_id: str,
    step_id: str,
    payload: StepDecisionIn | None = None,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _OPERATION_ROLES)
    try:
        return reject_step(
            db, _organization_id(ctx), run_id, step_id,
            actor_user_id=str(ctx.user.id),
            reason=payload.reason if payload else None,
        )
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.post("/runs/{run_id}/steps/{step_id}/complete")
def complete(
    run_id: str,
    step_id: str,
    payload: StepCompleteIn,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _OPERATION_ROLES)
    try:
        return complete_step(
            db, _organization_id(ctx), run_id, step_id,
            actor=str(ctx.user.id), result=payload.result, human_decision=True,
        )
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.put("/policy")
def policy(
    payload: PolicyIn,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_role(ctx, _POLICY_ROLES)
    try:
        return upsert_policy(
            db,
            _organization_id(ctx),
            workspace_id=payload.workspace_id,
            autonomy_level=payload.autonomy_level,
            action_class_caps=payload.action_class_caps,
            risk_caps=payload.risk_caps,
            constraints=payload.constraints,
            actor_user_id=str(ctx.user.id),
        )
    except (KeyError, ValueError) as exc:
        raise _handle(exc) from exc


@router.get("/contract")
def contract(ctx: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    _organization_id(ctx)
    return {
        "autonomy_levels": {
            "A0": "Observe",
            "A1": "Recommend",
            "A2": "Prepare",
            "A3": "Execute with approval",
            "A4": "Autonomous within policy",
            "A5": "Closed-loop autonomy",
        },
        "step_types": sorted(STEP_TYPES),
        "action_classes": sorted(ACTION_CLASSES),
        "risk_levels": sorted(RISK_LEVELS),
        "invariants": [
            "Model output cannot override deterministic policy.",
            "Approval never implies physical or external execution.",
            "Physical, regulated, financial, and destructive actions require explicit human approval in V1.",
            "External execution must be explicitly confirmed before verification.",
            "Verified outcome is separate from completed execution.",
        ],
    }

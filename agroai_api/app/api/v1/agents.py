"""Agent workflow API routes."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.orchestrator import AgentOrchestrator
from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.api_key_service import APIKeyService
from app.services.brain_commercial_runtime import install_brain_commercial_runtime
from app.services.commercial_control import require_feature
from app.services.quota import commit_reservation, release_reservation, reserve_quota


# Main loads the Brain router before this module. Bind the fully initialized Brain
# globals to the policy-aware runtime before the application starts serving requests.
install_brain_commercial_runtime()

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentContext:
    def __init__(self, orchestrator: AgentOrchestrator):
        self.orchestrator = orchestrator


def _context(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
) -> AgentContext:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent workflows require a verified server-side API key")
    api_key = APIKeyService.verify_api_key(db, x_api_key)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent API key")
    tenant_id = str(api_key.tenant_id)
    if x_organization_id and x_organization_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Organization-Id does not match authenticated tenant")
    return AgentContext(AgentOrchestrator(db, tenant_id))


class AgentRunIn(BaseModel):
    workflow_type: str = "assurance_audit"
    passport_id: str | None = None
    workbench_session_id: str | None = None
    priority: str = "normal"
    actor: str = "user"
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionDecisionIn(BaseModel):
    action_id: str
    actor: str = "user"


@router.post("/runs", status_code=201)
def create_run(payload: AgentRunIn, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    data = payload.model_dump()
    data.update(data.pop("payload") or {})
    try:
        if payload.workbench_session_id and not payload.passport_id:
            return context.orchestrator.triage_workbench_session(payload.workbench_session_id, actor=payload.actor)
        return context.orchestrator.create_run(data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.orchestrator.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent run not found") from exc


@router.get("/runs")
def list_runs(passport_id: str | None = Query(default=None), context: AgentContext = Depends(_context)) -> dict[str, Any]:
    return {"runs": context.orchestrator.list_runs(passport_id=passport_id)}


@router.post("/runs/{run_id}/approve-action")
def approve_action(run_id: str, payload: ActionDecisionIn, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.orchestrator.action_decision(run_id, payload.action_id, approved=True, actor=payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/reject-action")
def reject_action(run_id: str, payload: ActionDecisionIn, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.orchestrator.action_decision(run_id, payload.action_id, approved=False, actor=payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/assurance/passports/{passport_id}/triage", status_code=201)
def triage_assurance_passport(passport_id: str, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.orchestrator.triage_passport(passport_id, workflow_type="assurance_audit", actor="agent")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/workbench/sessions/{session_id}/triage", status_code=201)
def triage_workbench_session(session_id: str, context: AgentContext = Depends(_context)) -> dict[str, Any]:
    return context.orchestrator.triage_workbench_session(session_id, actor="agent")


@router.post("/actions/plan")
def user_action_plan(payload: dict[str, Any], ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Plan concrete work from a user request inside the authenticated portal."""
    from app.api.v1.agentic_actions import ActionPlanRequest, post_action_plan

    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    require_feature(db, ctx.organization, "agents.plan", recommended_plan="professional", allow_preview=True)
    return post_action_plan(ActionPlanRequest(**payload), ctx=ctx, db=db)


@router.post("/actions/execute")
def user_action_execute(payload: dict[str, Any], ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Execute commercially authorized work while preserving operational safety gates."""
    from app.api.v1.agentic_actions import APPROVAL_REQUIRED, ActionExecuteRequest, post_action_execute

    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")

    request = ActionExecuteRequest(**payload)
    approval_gated = request.action_type in APPROVAL_REQUIRED
    require_feature(
        db,
        ctx.organization,
        "agents.execute_approval_gated" if approval_gated else "agents.execute_safe",
        recommended_plan="team" if approval_gated else "professional",
    )

    # Planning an approval-required action does not consume execution capacity.
    # Capacity is reserved only when safe work executes or explicit approval is present.
    if approval_gated and not request.approval_confirmed:
        return post_action_execute(request, ctx=ctx, db=db)

    reservation = reserve_quota(
        db,
        ctx.organization,
        "agent_run",
        workspace_id=request.workspace_id,
        user_id=ctx.user.id,
        request_id=str((request.payload or {}).get("request_id") or uuid.uuid4()),
        metadata={"action_type": request.action_type, "approval_gated": approval_gated},
    )
    try:
        result = post_action_execute(request, ctx=ctx, db=db)
        if result.get("status") in {"executed", "approval_recorded"}:
            commit_reservation(
                db,
                reservation,
                event_type="agent_run",
                metadata={"result_status": result.get("status"), "action_type": request.action_type},
            )
        else:
            release_reservation(db, reservation, reason=f"result:{result.get('status') or 'unknown'}")
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise

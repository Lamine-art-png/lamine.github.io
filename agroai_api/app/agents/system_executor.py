"""Trusted server-side executor for policy-safe autonomous actions.

This is intentionally narrower than the interactive agentic executor. A worker
may create durable field work or compute readiness, but it cannot email people,
write new field evidence, or issue physical-controller commands. Those continue
to require the interactive/approval path until dedicated connector executors and
stronger policy envelopes exist.
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.agents.autonomy_runtime import AutonomousOperationsRuntime
from app.agents.models import AgentActionProposal, AgentWorkflowRun
from app.models.operational_records import IngestionJob
from app.models.saas import Organization
from app.services.commercial_control import require_feature
from app.services.field_operating_loop import TASK_JOB_TYPE
from app.services.quota import commit_reservation, release_reservation, reserve_quota


BACKGROUND_SAFE_ACTIONS = {
    "create_field_task",
    "collect_missing_evidence",
    "integration_readiness_check",
}


def _task_id(action_id: str) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:20]
    return f"task_auto_{digest}"


def _existing_task(db: Session, organization_id: str, action_id: str) -> IngestionJob | None:
    # Deterministic primary key closes the crash window between task persistence
    # and action-ledger acknowledgement without relying on JSON predicates.
    row = db.get(IngestionJob, _task_id(action_id))
    if row and row.tenant_id == organization_id and row.job_type == TASK_JOB_TYPE:
        return row
    return None


def _create_autonomy_task(
    db: Session,
    *,
    organization_id: str,
    workspace_id: str | None,
    run_id: str,
    action: AgentActionProposal,
    title: str,
    field: str | None,
    block: str | None,
    priority: str,
    why: str,
    instructions: list[str],
    evidence_required: list[str],
    created_from: str,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    existing = _existing_task(db, organization_id, action.id)
    if existing:
        return {"id": existing.id, "status": existing.status, **(existing.input_json or {})}

    job = IngestionJob(
        id=_task_id(action.id),
        tenant_id=organization_id,
        workspace_id=workspace_id,
        job_type=TASK_JOB_TYPE,
        status="open",
        input_json={
            "title": title[:180],
            "field": field,
            "block": block,
            "assigned_to": assigned_to,
            "priority": priority if priority in {"high", "medium", "low"} else "medium",
            "why": why[:1200],
            "instructions": [str(item)[:500] for item in instructions],
            "evidence_required": [str(item)[:220] for item in evidence_required],
            "created_from": created_from,
            "customer_safe": True,
            "workspace_id": workspace_id,
            "source_autonomy_run_id": run_id,
            "source_autonomy_action_id": action.id,
        },
        output_json={"created_by": "autonomous_operations_runtime"},
        idempotency_key=f"autonomy-task:{action.id}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"id": job.id, "status": job.status, **(job.input_json or {})}


def execute_background_action(
    db: Session,
    *,
    organization_id: str,
    workspace_id: str | None,
    run_id: str,
    action_id: str,
) -> dict[str, Any]:
    """Execute one safe action idempotently and update the canonical ledger."""
    run = (
        db.query(AgentWorkflowRun)
        .filter(
            AgentWorkflowRun.id == run_id,
            AgentWorkflowRun.organization_id == organization_id,
        )
        .first()
    )
    action = (
        db.query(AgentActionProposal)
        .filter(
            AgentActionProposal.id == action_id,
            AgentActionProposal.run_id == run_id,
            AgentActionProposal.organization_id == organization_id,
        )
        .first()
    )
    if not run or not action:
        raise ValueError("Autonomy run/action not found")
    if workspace_id is not None and run.workspace_id != workspace_id:
        raise ValueError("Autonomy run is outside the active workspace")
    workspace_id = run.workspace_id
    if action.workspace_id != run.workspace_id:
        raise ValueError("Autonomy action workspace does not match its run")
    if action.action_type not in BACKGROUND_SAFE_ACTIONS:
        return {"status": "not_executed", "reason": "background_action_not_permitted", "action_id": action.id}
    if action.requires_human_approval or action.status == "approval_required":
        return {"status": "approval_required", "action_id": action.id}
    if action.execution_status == "succeeded":
        return {"status": "already_executed", "action_id": action.id, "result": action.execution_result_json or {}}
    if action.status != "ready":
        return {"status": "not_executed", "reason": f"action_status:{action.status}", "action_id": action.id}

    organization = db.get(Organization, organization_id)
    if not organization:
        raise ValueError("Organization not found")
    require_feature(db, organization, "agents.execute_safe", recommended_plan="professional")
    reservation = reserve_quota(
        db,
        organization,
        "agent_run",
        workspace_id=workspace_id,
        user_id=None,
        request_id=f"autonomy-action:{action.id}",
        metadata={
            "execution_mode": "trusted_background",
            "autonomy_run_id": run_id,
            "autonomy_action_id": action.id,
            "action_type": action.action_type,
        },
    )

    runtime = AutonomousOperationsRuntime(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        actor_user_id=None,
    )
    runtime.begin_action(run_id, action.id)
    envelope = action.payload or {}
    data = envelope.get("payload") or {}
    try:
        if action.action_type == "create_field_task":
            task = _create_autonomy_task(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                run_id=run_id,
                action=action,
                title=str(data.get("title") or envelope.get("title") or "AGRO-AI field follow-up task"),
                field=data.get("field"),
                block=data.get("block"),
                assigned_to=data.get("assigned_to"),
                priority=str(data.get("priority") or "medium"),
                why=str(data.get("why") or envelope.get("description") or "Created by AGRO-AI autonomous operations"),
                instructions=list(data.get("instructions") or []),
                evidence_required=list(data.get("evidence_required") or ["field outcome", "timestamp", "verification evidence"]),
                created_from=str(data.get("created_from") or "field_update"),
            )
            result = {"status": "executed", "action_type": action.action_type, "created_task": task}
        elif action.action_type == "collect_missing_evidence":
            task = _create_autonomy_task(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                run_id=run_id,
                action=action,
                title="Collect missing evidence for autonomous workflow",
                field=data.get("field"),
                block=data.get("block"),
                assigned_to=data.get("assigned_to"),
                priority="medium",
                why=str(data.get("why") or data.get("answer") or data.get("question") or "AGRO-AI needs verified evidence before the workflow can close"),
                instructions=["Collect each required evidence item.", "Attach verified evidence before marking the workflow complete."],
                evidence_required=list(data.get("evidence_required") or ["field/block", "timestamp", "source system", "operator or sensor confirmation"]),
                created_from="missing_evidence",
            )
            result = {"status": "executed", "action_type": action.action_type, "created_task": task}
        else:
            result = {
                "status": "executed",
                "action_type": action.action_type,
                "readiness": {
                    "system_hint": data.get("system_hint"),
                    "required_before_live_action": ["connector record", "credential/OAuth status", "field mapping", "recent sync", "audit log"],
                    "safe_next_step": "Verify connector readiness before enabling any external action.",
                },
            }

        snapshot = runtime.record_action_result(run_id, action.id, succeeded=True, result=result)
        commit_reservation(
            db,
            reservation,
            event_type="agent_run",
            metadata={"result_status": "executed", "execution_mode": "trusted_background"},
        )
        db.commit()
        return {"status": "executed", "action_id": action.id, "snapshot": snapshot}
    except Exception:
        db.rollback()
        try:
            runtime = AutonomousOperationsRuntime(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                actor_user_id=None,
            )
            runtime.record_action_result(run_id, action.id, succeeded=False, result={"error": "background_executor_failed"})
        except Exception:
            db.rollback()
        try:
            reservation = reserve_quota(
                db,
                organization,
                "agent_run",
                workspace_id=workspace_id,
                user_id=None,
                request_id=f"autonomy-action:{action.id}",
            )
            release_reservation(db, reservation, reason="background_executor_failed")
            db.commit()
        except Exception:
            db.rollback()
        raise

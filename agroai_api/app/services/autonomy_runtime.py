"""Durable, policy-governed workflow runtime for AGRO-AI autonomous operations.

The runtime owns work from trigger to verified outcome. Model output may propose work,
but deterministic policy decides whether a step can execute, needs approval, or must
wait for external/physical confirmation.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.autonomy import AutonomyEvent, AutonomyPolicy, AutonomyProcedure, AutonomyRun, AutonomyStep
from app.models.operational_records import IngestionJob
from app.models.saas import Workspace

LEVELS = {"A0": 0, "A1": 1, "A2": 2, "A3": 3, "A4": 4, "A5": 5}
DEFAULT_LEVEL = "A4"
ACTION_CLASS_CAPS = {
    "intelligence": "A4",
    "software": "A4",
    "field_dispatch": "A4",
    "verification": "A4",
    "external_communication": "A3",
    "financial": "A3",
    "regulated": "A3",
    "physical_control": "A3",
    "destructive": "A1",
}
RISK_CAPS = {"low": "A4", "medium": "A4", "high": "A3", "critical": "A2"}
MANDATORY_APPROVAL_CLASSES = {"financial", "regulated", "physical_control", "destructive"}
ACTIVE_STATUSES = {"running", "waiting_approval", "waiting_external", "waiting_verification", "exception"}
STEP_TYPES = {"checkpoint", "task_dispatch", "external_action", "verification", "close"}
ACTION_CLASSES = set(ACTION_CLASS_CAPS)
RISK_LEVELS = set(RISK_CAPS)


def _step(key: str, name: str, step_type: str, *, action_class: str = "intelligence",
          action_type: str | None = None, risk: str = "low", minimum: str = "A4",
          approval_required: bool = False, template: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key, "name": name, "type": step_type, "action_class": action_class,
        "action_type": action_type, "risk": risk, "minimum_autonomy_level": minimum,
        "approval_required": approval_required, "template": template or {},
    }


SYSTEM_PROCEDURES: tuple[dict[str, Any], ...] = (
    {
        "key": "field_issue_resolution", "name": "Field Issue Resolution", "domain": "field_operations",
        "description": "Own a field issue from grounded observation through accountable work and verified closure.",
        "triggers": ["field_observation", "field_issue", "manual"],
        "steps": [
            _step("ground", "Ground field issue", "checkpoint"),
            _step("dispatch", "Dispatch accountable follow-up", "task_dispatch", action_class="field_dispatch", action_type="create_field_task"),
            _step("verify", "Verify field resolution", "verification", action_class="verification"),
            _step("close", "Close verified field loop", "close"),
        ],
        "outcome": {"primary_metric": "time_to_verified_resolution", "verified_outcome_required": True},
    },
    {
        "key": "assurance_gap_resolution", "name": "Assurance Gap Resolution", "domain": "assurance",
        "description": "Own a missing-proof gap from deterministic readiness finding through reviewed evidence closure.",
        "triggers": ["assurance_gap", "assurance_agent", "manual"],
        "steps": [
            _step("ground", "Ground proof gap", "checkpoint"),
            _step("collect", "Dispatch evidence collection", "task_dispatch", action_class="field_dispatch", action_type="collect_missing_evidence"),
            _step("verify", "Review new evidence", "verification", action_class="verification"),
            _step("close", "Close proof-resolution loop", "close"),
        ],
        "outcome": {"primary_metric": "time_to_readiness_gap_resolution", "verified_outcome_required": True},
    },
    {
        "key": "irrigation_operations", "name": "Irrigation Operations", "domain": "water",
        "description": "Move a grounded irrigation decision through controlled execution and planned-versus-actual verification.",
        "triggers": ["irrigation_decision", "water_exception", "manual"],
        "steps": [
            _step("decide", "Ground irrigation decision", "checkpoint"),
            _step("execute", "Authorize controller action", "external_action", action_class="physical_control",
                  action_type="request_controller_action", risk="high", minimum="A3", approval_required=True),
            _step("verify", "Verify applied irrigation", "verification", action_class="verification"),
            _step("close", "Close irrigation loop", "close"),
        ],
        "outcome": {"primary_metric": "verified_execution_rate", "verified_outcome_required": True},
    },
    {
        "key": "harvest_operations", "name": "Harvest Operations", "domain": "harvest",
        "description": "Own a harvest exception or readiness item through work dispatch and evidence-backed completion.",
        "triggers": ["harvest_readiness", "harvest_exception", "manual"],
        "steps": [
            _step("ground", "Ground harvest state", "checkpoint"),
            _step("dispatch", "Dispatch harvest work", "task_dispatch", action_class="field_dispatch", action_type="create_field_task"),
            _step("verify", "Verify harvest work", "verification", action_class="verification"),
            _step("close", "Close harvest loop", "close"),
        ],
        "outcome": {"primary_metric": "time_to_verified_harvest_action", "verified_outcome_required": True},
    },
    {
        "key": "finance_procurement_operations", "name": "Finance & Procurement Operations", "domain": "finance",
        "description": "Prepare purchasing work, preserve explicit financial approval, and verify reconciliation.",
        "triggers": ["procurement_need", "inventory_shortage", "manual"],
        "steps": [
            _step("ground", "Ground procurement need", "checkpoint"),
            _step("approve", "Authorize financial transaction", "external_action", action_class="financial",
                  action_type="financial_transaction", risk="high", minimum="A3", approval_required=True),
            _step("verify", "Reconcile transaction and field cost", "verification", action_class="verification"),
            _step("close", "Close procurement loop", "close"),
        ],
        "outcome": {"primary_metric": "time_to_reconciled_procurement", "verified_outcome_required": True},
    },
)


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _level(value: str | None) -> str:
    normalized = str(value or DEFAULT_LEVEL).upper()
    if normalized not in LEVELS:
        raise ValueError(f"Unsupported autonomy level: {value}")
    return normalized


def _lower_level(*values: str) -> str:
    return min(values, key=lambda item: LEVELS[_level(item)])


def ensure_system_procedures(db: Session) -> None:
    changed = False
    for spec in SYSTEM_PROCEDURES:
        row = (
            db.query(AutonomyProcedure)
            .filter(
                AutonomyProcedure.organization_id.is_(None),
                AutonomyProcedure.procedure_key == spec["key"],
                AutonomyProcedure.version == 1,
            )
            .first()
        )
        if row:
            continue
        db.add(AutonomyProcedure(
            id=f"procedure_system_{spec['key']}_v1",
            organization_id=None,
            procedure_key=spec["key"],
            version=1,
            name=spec["name"],
            domain=spec["domain"],
            description=spec["description"],
            source="system",
            active=True,
            trigger_types_json=spec["triggers"],
            steps_json=spec["steps"],
            outcome_contract_json=spec["outcome"],
            metadata_json={"runtime_version": "autonomy-v1"},
        ))
        changed = True
    if changed:
        db.commit()


def resolve_policy(db: Session, organization_id: str, workspace_id: str | None = None) -> AutonomyPolicy:
    query = db.query(AutonomyPolicy).filter(
        AutonomyPolicy.organization_id == organization_id,
        AutonomyPolicy.enabled.is_(True),
    )
    if workspace_id:
        scoped = query.filter(AutonomyPolicy.workspace_id == workspace_id).first()
        if scoped:
            return scoped
    default = query.filter(AutonomyPolicy.workspace_id.is_(None)).first()
    if default:
        return default
    default = AutonomyPolicy(
        id=_uuid("policy"), organization_id=organization_id, workspace_id=None,
        autonomy_level=DEFAULT_LEVEL, action_class_caps_json=dict(ACTION_CLASS_CAPS),
        risk_caps_json=dict(RISK_CAPS),
        constraints_json={
            "physical_execution_requires_explicit_confirmation": True,
            "regulated_actions_require_human_approval": True,
            "financial_actions_require_human_approval": True,
        },
        enabled=True,
    )
    db.add(default)
    db.commit()
    db.refresh(default)
    return default


def upsert_policy(db: Session, organization_id: str, *, workspace_id: str | None,
                  autonomy_level: str, action_class_caps: dict[str, str] | None = None,
                  risk_caps: dict[str, str] | None = None, constraints: dict[str, Any] | None = None,
                  actor_user_id: str | None = None) -> dict[str, Any]:
    if workspace_id:
        _require_workspace(db, organization_id, workspace_id)
    row = db.query(AutonomyPolicy).filter(
        AutonomyPolicy.organization_id == organization_id,
        AutonomyPolicy.workspace_id == workspace_id,
    ).first()
    if not row:
        row = AutonomyPolicy(id=_uuid("policy"), organization_id=organization_id, workspace_id=workspace_id)
        db.add(row)
    row.autonomy_level = _level(autonomy_level)
    row.action_class_caps_json = _validate_caps(action_class_caps or ACTION_CLASS_CAPS, ACTION_CLASSES)
    row.risk_caps_json = _validate_caps(risk_caps or RISK_CAPS, RISK_LEVELS)
    row.constraints_json = constraints or {
        "physical_execution_requires_explicit_confirmation": True,
        "regulated_actions_require_human_approval": True,
        "financial_actions_require_human_approval": True,
    }
    row.enabled = True
    row.created_by = actor_user_id or row.created_by
    db.commit()
    db.refresh(row)
    return serialize_policy(row)


def _validate_caps(values: dict[str, str], allowed: set[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in values.items():
        if key not in allowed:
            raise ValueError(f"Unsupported policy key: {key}")
        output[key] = _level(value)
    return output


def create_custom_procedure(db: Session, organization_id: str, *, name: str, domain: str,
                            steps: list[dict[str, Any]], trigger_types: list[str] | None = None,
                            description: str | None = None, procedure_key: str | None = None,
                            outcome_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    if not 1 <= len(steps) <= 32:
        raise ValueError("A procedure must contain between 1 and 32 steps")
    key = re.sub(r"[^a-z0-9]+", "_", (procedure_key or name).lower()).strip("_")
    if not key or len(key) > 120:
        raise ValueError("Invalid procedure key")
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        step_type = str(step.get("type") or "").strip()
        action_class = str(step.get("action_class") or "intelligence").strip()
        risk = str(step.get("risk") or "low").strip()
        minimum = _level(step.get("minimum_autonomy_level") or "A4")
        if step_type not in STEP_TYPES:
            raise ValueError(f"Unsupported step type at position {index + 1}: {step_type}")
        if action_class not in ACTION_CLASSES:
            raise ValueError(f"Unsupported action class at position {index + 1}: {action_class}")
        if risk not in RISK_LEVELS:
            raise ValueError(f"Unsupported risk level at position {index + 1}: {risk}")
        normalized.append(_step(
            re.sub(r"[^a-z0-9]+", "_", str(step.get("key") or f"step_{index + 1}").lower()).strip("_"),
            str(step.get("name") or f"Step {index + 1}")[:220],
            step_type,
            action_class=action_class,
            action_type=str(step.get("action_type") or "") or None,
            risk=risk,
            minimum=minimum,
            approval_required=bool(step.get("approval_required")),
            template=dict(step.get("template") or {}),
        ))
    if normalized[-1]["type"] != "close":
        raise ValueError("The final procedure step must be a close step")
    latest = (
        db.query(AutonomyProcedure)
        .filter(AutonomyProcedure.organization_id == organization_id, AutonomyProcedure.procedure_key == key)
        .order_by(AutonomyProcedure.version.desc()).first()
    )
    if latest:
        latest.active = False
    version = (latest.version + 1) if latest else 1
    row = AutonomyProcedure(
        id=_uuid("procedure"), organization_id=organization_id, procedure_key=key, version=version,
        name=name[:220], domain=domain[:80], description=description, source="customer", active=True,
        trigger_types_json=trigger_types or ["manual"], steps_json=normalized,
        outcome_contract_json=outcome_contract or {"verified_outcome_required": True}, metadata_json={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_procedure(row)


def list_procedures(db: Session, organization_id: str) -> list[dict[str, Any]]:
    ensure_system_procedures(db)
    rows = (
        db.query(AutonomyProcedure)
        .filter(
            AutonomyProcedure.active.is_(True),
            or_(AutonomyProcedure.organization_id.is_(None), AutonomyProcedure.organization_id == organization_id),
        )
        .order_by(AutonomyProcedure.domain.asc(), AutonomyProcedure.name.asc()).all()
    )
    return [serialize_procedure(row) for row in rows]


def _procedure(db: Session, organization_id: str, procedure_key: str) -> AutonomyProcedure:
    ensure_system_procedures(db)
    row = (
        db.query(AutonomyProcedure)
        .filter(
            AutonomyProcedure.procedure_key == procedure_key,
            AutonomyProcedure.active.is_(True),
            or_(AutonomyProcedure.organization_id.is_(None), AutonomyProcedure.organization_id == organization_id),
        )
        .order_by(AutonomyProcedure.organization_id.desc(), AutonomyProcedure.version.desc()).first()
    )
    if not row:
        raise KeyError(procedure_key)
    return row


def start_run(db: Session, organization_id: str, *, procedure_key: str, workspace_id: str | None,
              trigger_type: str, trigger_ref: str | None = None, context: dict[str, Any] | None = None,
              requested_autonomy_level: str | None = None, actor: str = "system") -> dict[str, Any]:
    if workspace_id:
        _require_workspace(db, organization_id, workspace_id)
    procedure = _procedure(db, organization_id, procedure_key)
    allowed_triggers = set(procedure.trigger_types_json or [])
    if allowed_triggers and trigger_type not in allowed_triggers:
        raise ValueError(f"Trigger {trigger_type!r} is not allowed for {procedure_key}")
    if trigger_ref:
        existing = (
            db.query(AutonomyRun)
            .filter(
                AutonomyRun.organization_id == organization_id,
                AutonomyRun.procedure_key == procedure_key,
                AutonomyRun.trigger_type == trigger_type,
                AutonomyRun.trigger_ref == trigger_ref,
                AutonomyRun.status.in_(ACTIVE_STATUSES | {"completed"}),
            )
            .order_by(AutonomyRun.created_at.desc()).first()
        )
        if existing:
            return serialize_run(db, existing)
    policy = resolve_policy(db, organization_id, workspace_id)
    requested = _level(requested_autonomy_level or policy.autonomy_level)
    effective = _lower_level(requested, policy.autonomy_level)
    run = AutonomyRun(
        id=_uuid("autrun"), organization_id=organization_id, workspace_id=workspace_id,
        procedure_id=procedure.id, procedure_key=procedure.procedure_key,
        trigger_type=trigger_type, trigger_ref=trigger_ref, status="running",
        requested_autonomy_level=requested, effective_autonomy_level=effective,
        current_step_sequence=0, eligible_for_autonomy=True, human_decision_count=0,
        exception_count=0, context_json=context or {}, result_json={},
    )
    db.add(run)
    db.flush()
    for sequence, spec in enumerate(procedure.steps_json or []):
        db.add(AutonomyStep(
            id=_uuid("autstep"), run_id=run.id, organization_id=organization_id, sequence=sequence,
            step_key=str(spec.get("key") or f"step_{sequence + 1}"), name=str(spec.get("name") or f"Step {sequence + 1}"),
            step_type=str(spec.get("type") or "checkpoint"), action_class=str(spec.get("action_class") or "intelligence"),
            action_type=spec.get("action_type"), risk_level=str(spec.get("risk") or "low"),
            minimum_autonomy_level=_level(spec.get("minimum_autonomy_level") or "A4"),
            status="pending", approval_required=bool(spec.get("approval_required")),
            idempotency_key=f"{run.id}:{sequence}", input_json=dict(spec.get("template") or {}), output_json={},
        ))
    _event(db, run, "workflow_started", actor, {"procedure_key": procedure_key, "trigger_type": trigger_type, "trigger_ref": trigger_ref})
    db.commit()
    db.refresh(run)
    _advance(db, run, policy, actor=actor)
    return serialize_run(db, run)


def _effective_for_step(run: AutonomyRun, step: AutonomyStep, policy: AutonomyPolicy) -> str:
    class_cap = (policy.action_class_caps_json or {}).get(step.action_class, ACTION_CLASS_CAPS.get(step.action_class, "A1"))
    risk_cap = (policy.risk_caps_json or {}).get(step.risk_level, RISK_CAPS.get(step.risk_level, "A1"))
    return _lower_level(run.effective_autonomy_level, class_cap, risk_cap)


def _approval_required(step: AutonomyStep, effective: str) -> bool:
    if step.approval_required or step.action_class in MANDATORY_APPROVAL_CLASSES:
        return True
    return LEVELS[effective] < LEVELS[_level(step.minimum_autonomy_level)]


def _advance(db: Session, run: AutonomyRun, policy: AutonomyPolicy, *, actor: str) -> None:
    while run.status == "running":
        step = (
            db.query(AutonomyStep)
            .filter(AutonomyStep.run_id == run.id, AutonomyStep.sequence == run.current_step_sequence)
            .first()
        )
        if step is None:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.outcome_status = run.outcome_status or "completed"
            _event(db, run, "workflow_completed", actor, {"reason": "no_remaining_steps"})
            db.commit()
            return
        effective = _effective_for_step(run, step, policy)
        step.effective_autonomy_level = effective
        needs_approval = _approval_required(step, effective)
        if step.step_type == "checkpoint":
            _finish_step(db, run, step, actor, {"grounded": True, "context_ref": run.trigger_ref})
            continue
        if step.step_type == "task_dispatch":
            if needs_approval:
                _wait_for_approval(db, run, step, actor)
                return
            _execute_task_dispatch(db, run, step, actor)
            continue
        if step.step_type == "external_action":
            # V1 deliberately separates approval from external/physical execution.
            _wait_for_approval(db, run, step, actor)
            return
        if step.step_type == "verification":
            step.status = "waiting_verification"
            step.started_at = step.started_at or datetime.utcnow()
            run.status = "waiting_verification"
            run.verification_status = "pending"
            _event(db, run, "verification_requested", actor, {"step_id": step.id})
            db.commit()
            return
        if step.step_type == "close":
            verified = run.verification_status == "verified"
            step.status = "completed"
            step.started_at = step.started_at or datetime.utcnow()
            step.completed_at = datetime.utcnow()
            step.output_json = {"workflow_owned_end_to_end": True, "verified": verified}
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.outcome_status = "verified_complete" if verified else "completed"
            _event(db, run, "workflow_completed", actor, {
                "verified": verified, "human_decision_count": run.human_decision_count,
                "autonomous": bool(run.eligible_for_autonomy and run.human_decision_count == 0),
            }, step=step)
            db.commit()
            return
        run.status = "exception"
        run.exception_count += 1
        run.failure_reason = f"Unsupported step type: {step.step_type}"
        _event(db, run, "workflow_exception", actor, {"reason": run.failure_reason}, step=step)
        db.commit()
        return


def _wait_for_approval(db: Session, run: AutonomyRun, step: AutonomyStep, actor: str) -> None:
    step.status = "waiting_approval"
    step.approval_required = True
    step.started_at = step.started_at or datetime.utcnow()
    run.status = "waiting_approval"
    _event(db, run, "approval_requested", actor, {
        "step_id": step.id, "action_class": step.action_class, "risk_level": step.risk_level,
        "physical_or_external_action_executed": False,
    }, step=step)
    db.commit()


def _execute_task_dispatch(db: Session, run: AutonomyRun, step: AutonomyStep, actor: str) -> None:
    context = dict(run.context_json or {})
    existing_id = context.get("existing_task_id") or context.get("task_id")
    if existing_id:
        existing = db.query(IngestionJob).filter(
            IngestionJob.tenant_id == run.organization_id,
            IngestionJob.id == str(existing_id),
            IngestionJob.job_type == "field_ops_task",
        ).first()
        if existing:
            existing.input_json = {
                **(existing.input_json or {}),
                "autonomy_run_id": run.id,
                "autonomy_step_id": step.id,
            }
            _finish_step(db, run, step, actor, {"task_id": existing.id, "linked_existing_task": True})
            return
    title = str(context.get("task_title") or context.get("recommended_action") or context.get("summary") or step.name)[:180]
    task = IngestionJob(
        id=f"task_{uuid.uuid4().hex[:12]}", tenant_id=run.organization_id, workspace_id=run.workspace_id,
        job_type="field_ops_task", status="open",
        input_json={
            "title": title,
            "field": context.get("field_name") or context.get("field"),
            "block": context.get("block_name") or context.get("block"),
            "assigned_to": context.get("assigned_to"),
            "priority": context.get("priority") or "medium",
            "why": str(context.get("summary") or context.get("why") or "AGRO-AI autonomous workflow follow-through")[:1200],
            "instructions": list(context.get("instructions") or [context.get("recommended_action") or "Complete the accountable field follow-up."]),
            "evidence_required": list(context.get("evidence_required") or []),
            "created_from": "autonomy_runtime",
            "customer_safe": True,
            "workspace_id": run.workspace_id,
            "autonomy_run_id": run.id,
            "autonomy_step_id": step.id,
            "source_observation_id": context.get("observation_id"),
            "source_passport_id": context.get("passport_id"),
        },
        output_json={"source": "autonomy_runtime", "run_id": run.id, "step_id": step.id},
    )
    db.add(task)
    db.flush()
    _finish_step(db, run, step, actor, {"task_id": task.id, "linked_existing_task": False})


def _finish_step(db: Session, run: AutonomyRun, step: AutonomyStep, actor: str, output: dict[str, Any]) -> None:
    step.status = "completed"
    step.started_at = step.started_at or datetime.utcnow()
    step.completed_at = datetime.utcnow()
    step.output_json = output
    step.attempt_count += 1
    _event(db, run, "step_completed", actor, output, step=step)
    run.current_step_sequence = step.sequence + 1
    run.status = "running"
    db.commit()
    policy = resolve_policy(db, run.organization_id, run.workspace_id)
    _advance(db, run, policy, actor=actor)


def approve_step(db: Session, organization_id: str, run_id: str, step_id: str, *, actor_user_id: str) -> dict[str, Any]:
    run, step = _scoped_step(db, organization_id, run_id, step_id)
    if step.status != "waiting_approval":
        raise ValueError("Step is not waiting for approval")
    step.approved_by = actor_user_id
    step.approved_at = datetime.utcnow()
    run.human_decision_count += 1
    _event(db, run, "approval_granted", actor_user_id, {"step_id": step.id}, step=step)
    if step.step_type == "task_dispatch":
        run.status = "running"
        db.commit()
        _execute_task_dispatch(db, run, step, actor_user_id)
    elif step.step_type == "external_action":
        step.status = "waiting_external"
        run.status = "waiting_external"
        step.output_json = {
            "approval_recorded": True,
            "physical_or_external_action_executed": False,
            "action_type": step.action_type,
        }
        _event(db, run, "external_execution_requested", actor_user_id, step.output_json, step=step)
        db.commit()
    else:
        _finish_step(db, run, step, actor_user_id, {"approval_recorded": True})
    return serialize_run(db, run)


def reject_step(db: Session, organization_id: str, run_id: str, step_id: str, *, actor_user_id: str, reason: str | None = None) -> dict[str, Any]:
    run, step = _scoped_step(db, organization_id, run_id, step_id)
    if step.status != "waiting_approval":
        raise ValueError("Step is not waiting for approval")
    step.status = "rejected"
    step.rejected_at = datetime.utcnow()
    step.error = reason or "Rejected by operator"
    run.human_decision_count += 1
    run.status = "exception"
    run.exception_count += 1
    run.failure_reason = step.error
    _event(db, run, "approval_rejected", actor_user_id, {"step_id": step.id, "reason": step.error}, step=step)
    db.commit()
    return serialize_run(db, run)


def complete_step(db: Session, organization_id: str, run_id: str, step_id: str, *, actor: str,
                  result: dict[str, Any]) -> dict[str, Any]:
    run, step = _scoped_step(db, organization_id, run_id, step_id)
    if step.status not in {"waiting_external", "waiting_verification"}:
        raise ValueError("Step is not waiting for external execution or verification")
    if step.status == "waiting_external":
        executed = result.get("executed") is True or str(result.get("execution_status") or "").lower() in {"executed", "completed", "applied"}
        if not executed:
            raise ValueError("External execution must be explicitly confirmed before the workflow can advance")
        payload = dict(result)
        payload["physical_or_external_action_executed"] = True
        _finish_step(db, run, step, actor, payload)
        return serialize_run(db, run)
    verified = result.get("verified") is True or str(result.get("verification_status") or "").lower() in {"verified", "complete", "matched"}
    run.verification_status = "verified" if verified else str(result.get("verification_status") or "not_verified")
    if verified:
        _finish_step(db, run, step, actor, dict(result))
        return serialize_run(db, run)

    # A failed verification is an exception, not a successful close. The
    # operator can resolve the exception with new evidence and a later run.
    step.status = "completed"
    step.started_at = step.started_at or datetime.utcnow()
    step.completed_at = datetime.utcnow()
    step.output_json = dict(result)
    step.attempt_count += 1
    run.current_step_sequence = step.sequence + 1
    run.status = "exception"
    run.outcome_status = str(result.get("outcome_status") or "verification_failed")
    run.exception_count += 1
    run.failure_reason = str(result.get("reason") or "Outcome verification did not pass")
    _event(db, run, "verification_failed", actor, dict(result), step=step)
    db.commit()
    return serialize_run(db, run)


def list_runs(db: Session, organization_id: str, *, workspace_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    query = db.query(AutonomyRun).filter(AutonomyRun.organization_id == organization_id)
    if workspace_id:
        query = query.filter(AutonomyRun.workspace_id == workspace_id)
    rows = query.order_by(AutonomyRun.updated_at.desc()).limit(max(1, min(limit, 100))).all()
    return [serialize_run(db, row) for row in rows]


def get_run(db: Session, organization_id: str, run_id: str) -> dict[str, Any]:
    row = db.query(AutonomyRun).filter(AutonomyRun.organization_id == organization_id, AutonomyRun.id == run_id).first()
    if not row:
        raise KeyError(run_id)
    return serialize_run(db, row)


def autonomy_summary(db: Session, organization_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    policy = resolve_policy(db, organization_id, workspace_id)
    query = db.query(AutonomyRun).filter(AutonomyRun.organization_id == organization_id)
    if workspace_id:
        query = query.filter(AutonomyRun.workspace_id == workspace_id)
    active = query.filter(AutonomyRun.status.in_(ACTIVE_STATUSES)).all()
    cutoff = datetime.utcnow() - timedelta(days=30)
    completed = query.filter(AutonomyRun.status == "completed", AutonomyRun.completed_at >= cutoff).all()
    eligible = [row for row in completed if row.eligible_for_autonomy]
    autonomous = [row for row in eligible if row.human_decision_count == 0]
    verified = [row for row in completed if row.verification_status == "verified"]
    def pct(n: int, d: int) -> float | None:
        return round((n / d) * 100.0, 1) if d else None
    return {
        "status": "ok",
        "policy": serialize_policy(policy),
        "active_workflows": len(active),
        "waiting_approval": len([row for row in active if row.status == "waiting_approval"]),
        "waiting_external": len([row for row in active if row.status == "waiting_external"]),
        "waiting_verification": len([row for row in active if row.status == "waiting_verification"]),
        "exceptions": len([row for row in active if row.status == "exception"]),
        "completed_30d": len(completed),
        "eligible_completed_30d": len(eligible),
        "autonomous_completed_30d": len(autonomous),
        "autonomous_completion_rate": pct(len(autonomous), len(eligible)),
        "verified_completion_rate": pct(len(verified), len(completed)),
        "metric_definition": "Eligible workflows completed end-to-end with zero human decisions, divided by all eligible completed workflows.",
        "recent_runs": [serialize_run(db, row, include_events=False) for row in query.order_by(AutonomyRun.updated_at.desc()).limit(8).all()],
    }


def _scoped_step(db: Session, organization_id: str, run_id: str, step_id: str) -> tuple[AutonomyRun, AutonomyStep]:
    run = db.query(AutonomyRun).filter(AutonomyRun.organization_id == organization_id, AutonomyRun.id == run_id).first()
    if not run:
        raise KeyError(run_id)
    step = db.query(AutonomyStep).filter(
        AutonomyStep.organization_id == organization_id, AutonomyStep.run_id == run.id, AutonomyStep.id == step_id
    ).first()
    if not step:
        raise KeyError(step_id)
    return run, step


def _require_workspace(db: Session, organization_id: str, workspace_id: str) -> Workspace:
    row = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.organization_id == organization_id).first()
    if not row:
        raise KeyError(workspace_id)
    return row


def _event(db: Session, run: AutonomyRun, event_type: str, actor: str, payload: dict[str, Any],
           *, step: AutonomyStep | None = None) -> None:
    db.add(AutonomyEvent(
        id=_uuid("autevent"), run_id=run.id, step_id=step.id if step else None,
        organization_id=run.organization_id, event_type=event_type, actor=str(actor or "system")[:160],
        payload_json=payload,
    ))


def serialize_policy(row: AutonomyPolicy) -> dict[str, Any]:
    return {
        "id": row.id, "workspace_id": row.workspace_id, "autonomy_level": row.autonomy_level,
        "action_class_caps": row.action_class_caps_json or {}, "risk_caps": row.risk_caps_json or {},
        "constraints": row.constraints_json or {}, "enabled": row.enabled,
    }


def serialize_procedure(row: AutonomyProcedure) -> dict[str, Any]:
    return {
        "id": row.id, "procedure_key": row.procedure_key, "version": row.version, "name": row.name,
        "domain": row.domain, "description": row.description, "source": row.source,
        "trigger_types": row.trigger_types_json or [], "steps": row.steps_json or [],
        "outcome_contract": row.outcome_contract_json or {},
    }


def serialize_run(db: Session, row: AutonomyRun, *, include_events: bool = True) -> dict[str, Any]:
    steps = db.query(AutonomyStep).filter(AutonomyStep.run_id == row.id).order_by(AutonomyStep.sequence.asc()).all()
    current = next((step for step in steps if step.sequence == row.current_step_sequence), None)
    payload: dict[str, Any] = {
        "id": row.id, "workspace_id": row.workspace_id, "procedure_key": row.procedure_key,
        "trigger_type": row.trigger_type, "trigger_ref": row.trigger_ref, "status": row.status,
        "requested_autonomy_level": row.requested_autonomy_level, "effective_autonomy_level": row.effective_autonomy_level,
        "eligible_for_autonomy": row.eligible_for_autonomy, "human_decision_count": row.human_decision_count,
        "exception_count": row.exception_count, "outcome_status": row.outcome_status,
        "verification_status": row.verification_status, "failure_reason": row.failure_reason,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "current_step": serialize_step(current) if current else None,
        "steps": [serialize_step(step) for step in steps],
    }
    if include_events:
        events = db.query(AutonomyEvent).filter(AutonomyEvent.run_id == row.id).order_by(AutonomyEvent.created_at.asc()).all()
        payload["events"] = [{
            "id": event.id, "step_id": event.step_id, "event_type": event.event_type,
            "actor": event.actor, "payload": event.payload_json or {},
            "created_at": event.created_at.isoformat() if event.created_at else None,
        } for event in events]
    return payload


def serialize_step(step: AutonomyStep | None) -> dict[str, Any] | None:
    if not step:
        return None
    return {
        "id": step.id, "sequence": step.sequence, "step_key": step.step_key, "name": step.name,
        "step_type": step.step_type, "action_class": step.action_class, "action_type": step.action_type,
        "risk_level": step.risk_level, "minimum_autonomy_level": step.minimum_autonomy_level,
        "effective_autonomy_level": step.effective_autonomy_level, "status": step.status,
        "approval_required": step.approval_required, "approved_by": step.approved_by,
        "approved_at": step.approved_at.isoformat() if step.approved_at else None,
        "output": step.output_json or {}, "error": step.error,
    }

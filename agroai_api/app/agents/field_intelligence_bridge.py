"""Durable bridge from completed Field Intelligence observations to Procedures.

The bridge uses IngestionJob as an outbox so the observation and its future
autonomy trigger are committed atomically, while Procedure execution happens in
a separate retryable worker transaction. This prevents automation failures from
corrupting Field Intelligence and prevents completed observations from being
silently dropped when the autonomy runtime is temporarily unavailable.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.autonomy_runtime import AutonomousOperationsRuntime
from app.agents.models import AgentProcedure
from app.agents.system_executor import execute_background_action
from app.models.field_intelligence import FieldObservation
from app.models.operational_records import IngestionJob

logger = logging.getLogger(__name__)

AUTONOMY_TRIGGER_JOB_TYPE = "autonomy_field_observation_trigger"
AUTONOMY_TRIGGER_MAX_ATTEMPTS = 8
AUTONOMY_TRIGGER_LEASE_SECONDS = 180
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def enqueue_completed_observation(db: Session, observation: FieldObservation) -> IngestionJob | None:
    """Stage one idempotent autonomy trigger in the caller's transaction."""
    if observation.status != "completed":
        return None
    idempotency_key = f"fi-autonomy:{observation.id}"
    existing = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == observation.tenant_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        return existing
    job = IngestionJob(
        id=f"auto_trigger_{uuid.uuid4().hex[:16]}",
        tenant_id=observation.tenant_id,
        workspace_id=observation.workspace_id,
        job_type=AUTONOMY_TRIGGER_JOB_TYPE,
        status="queued",
        input_json={
            "observation_id": observation.id,
            "workspace_id": observation.workspace_id,
            "source_type": "field_observation",
        },
        output_json={},
        idempotency_key=idempotency_key,
        attempt_count=0,
        max_attempts=AUTONOMY_TRIGGER_MAX_ATTEMPTS,
        next_attempt_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()
    return job


def _claim(db: Session, job_id: str, worker_id: str) -> IngestionJob | None:
    now = datetime.utcnow()
    updated = (
        db.query(IngestionJob)
        .filter(IngestionJob.id == job_id)
        .filter(IngestionJob.job_type == AUTONOMY_TRIGGER_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .update(
            {
                IngestionJob.status: "running",
                IngestionJob.worker_id: worker_id,
                IngestionJob.attempt_count: IngestionJob.attempt_count + 1,
                IngestionJob.lease_expires_at: now + timedelta(seconds=AUTONOMY_TRIGGER_LEASE_SECONDS),
                IngestionJob.last_heartbeat_at: now,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if updated != 1:
        return None
    return db.get(IngestionJob, job_id)


def _matches(procedure: AgentProcedure, observation: FieldObservation) -> bool:
    definition = procedure.definition_json or {}
    when = definition.get("when") or {}
    event_types = {str(value).strip().lower() for value in when.get("event_types") or [] if str(value).strip()}
    if event_types and str(observation.event_type or "").strip().lower() not in event_types:
        return False
    minimum_confidence = when.get("minimum_confidence")
    if isinstance(minimum_confidence, (int, float)) and float(observation.confidence or 0.0) < float(minimum_confidence):
        return False
    minimum_severity = str(when.get("minimum_severity") or "").strip().lower()
    if minimum_severity:
        observed = _SEVERITY_ORDER.get(str(observation.severity or "low").lower(), 0)
        required = _SEVERITY_ORDER.get(minimum_severity, 0)
        if observed < required:
            return False
    return True


def _render(value: Any, observation: FieldObservation) -> Any:
    if isinstance(value, str):
        replacements = {
            "{{observation_id}}": observation.id,
            "{{event_type}}": observation.event_type or "field observation",
            "{{field_name}}": observation.field_name or "field",
            "{{block_name}}": observation.block_name or "",
            "{{crop}}": observation.crop or "",
            "{{severity}}": observation.severity or "",
            "{{summary}}": observation.summary or "",
            "{{recommended_action}}": observation.recommended_action or "",
        }
        rendered = value
        for token, replacement in replacements.items():
            rendered = rendered.replace(token, str(replacement))
        return rendered
    if isinstance(value, list):
        return [_render(item, observation) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, observation) for key, item in value.items()}
    return value


def _default_steps(observation: FieldObservation) -> list[dict[str, Any]]:
    """Safe useful behavior when an enterprise activates a FI Procedure without steps."""
    return [
        {
            "key": "dispatch_follow_up",
            "action_type": "create_field_task",
            "title": "Resolve {{event_type}} — {{field_name}}",
            "description": "Dispatch the field follow-up and keep the workflow open until verified evidence confirms the outcome.",
            "risk_level": "low",
            "payload": {
                "title": "Resolve {{event_type}} — {{field_name}}",
                "field": "{{field_name}}",
                "block": "{{block_name}}",
                "priority": "high" if str(observation.severity or "").lower() in {"high", "critical"} else "medium",
                "why": "{{summary}}",
                "instructions": [
                    "Review the Field Intelligence observation and source evidence.",
                    "Perform the required field follow-up.",
                    "Attach verification evidence before closing the work.",
                ],
                "evidence_required": ["timestamp", "field/block", "post-action photo, sensor record, or operator evidence"],
                "created_from": "field_update",
            },
        }
    ]


def _process_trigger(db: Session, job: IngestionJob) -> dict[str, Any]:
    observation_id = str((job.input_json or {}).get("observation_id") or "")
    observation = db.get(FieldObservation, observation_id)
    if not observation or observation.tenant_id != job.tenant_id:
        return {"status": "skipped", "reason": "observation_missing"}
    if observation.status != "completed":
        return {"status": "skipped", "reason": f"observation_status:{observation.status}"}

    procedures = (
        db.query(AgentProcedure)
        .filter(
            AgentProcedure.organization_id == observation.tenant_id,
            AgentProcedure.status == "active",
            AgentProcedure.trigger_type == "field_observation",
        )
        .order_by(AgentProcedure.created_at.asc())
        .all()
    )
    procedures = [
        row for row in procedures
        if row.workspace_id in {None, observation.workspace_id} and _matches(row, observation)
    ]
    results: list[dict[str, Any]] = []
    for procedure in procedures:
        runtime = AutonomousOperationsRuntime(
            db,
            organization_id=observation.tenant_id,
            workspace_id=observation.workspace_id,
            actor_user_id=None,
        )
        run_key = f"fi:{observation.id}:procedure:{procedure.id}:v{procedure.version}"
        snapshot = runtime.start_run(
            procedure_id=procedure.id,
            idempotency_key=run_key,
            source_type="field_observation",
            source_id=observation.id,
            priority="critical" if observation.severity == "critical" else "high" if observation.severity == "high" else "normal",
            payload={
                "observation_id": observation.id,
                "field_name": observation.field_name,
                "block_name": observation.block_name,
                "crop": observation.crop,
                "event_type": observation.event_type,
                "severity": observation.severity,
                "confidence": observation.confidence,
                "summary": observation.summary,
                "recommended_action": observation.recommended_action,
                "evidence_ids": observation.evidence_ids_json or [],
                "provenance": observation.provenance_json or {},
            },
        )
        definition = procedure.definition_json or {}
        steps = definition.get("steps") or _default_steps(observation)
        action_results: list[dict[str, Any]] = []
        for index, raw_step in enumerate(steps[:10]):
            if not isinstance(raw_step, dict):
                continue
            step = _render(raw_step, observation)
            action_type = str(step.get("action_type") or "collect_missing_evidence")
            step_key = str(step.get("key") or f"step_{index + 1}")
            action = runtime.plan_action(
                snapshot["run"]["id"],
                action_type=action_type,
                idempotency_key=f"{run_key}:step:{step_key}",
                title=str(step.get("title") or f"AGRO-AI {action_type}"),
                description=str(step.get("description") or observation.summary or "Autonomous field workflow action"),
                risk_level=str(step.get("risk_level") or "low"),
                payload=step.get("payload") or {},
            )
            execution = {"status": "planned", "action_id": action["id"]}
            if action["status"] == "ready":
                execution = execute_background_action(
                    db,
                    organization_id=observation.tenant_id,
                    workspace_id=observation.workspace_id,
                    run_id=snapshot["run"]["id"],
                    action_id=action["id"],
                )
            action_results.append({"step": step_key, "action_id": action["id"], "execution": execution})
            # Approval is a hard workflow barrier. Do not plan later steps that
            # could depend on a decision that has not happened yet.
            if action["status"] == "approval_required":
                break
        results.append({"procedure_id": procedure.id, "run_id": snapshot["run"]["id"], "actions": action_results})
    return {"status": "processed", "observation_id": observation.id, "procedures": results}


def run_trigger_jobs(db: Session, *, limit: int = 25, worker_id: str | None = None) -> dict[str, Any]:
    worker_id = worker_id or f"autonomy-trigger-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    candidates = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == AUTONOMY_TRIGGER_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )
    processed = 0
    failed = 0
    for candidate in candidates:
        job = _claim(db, candidate.id, worker_id)
        if not job:
            continue
        try:
            result = _process_trigger(db, job)
            job = db.get(IngestionJob, job.id)
            if not job:
                continue
            job.status = "completed"
            job.output_json = result
            job.completed_at = datetime.utcnow()
            job.lease_expires_at = None
            job.worker_id = None
            db.commit()
            processed += 1
        except Exception as exc:  # noqa: BLE001 - durable retry boundary
            db.rollback()
            job = db.get(IngestionJob, candidate.id)
            if not job:
                failed += 1
                continue
            attempt = int(job.attempt_count or 0)
            terminal = attempt >= int(job.max_attempts or AUTONOMY_TRIGGER_MAX_ATTEMPTS)
            job.error = f"{exc.__class__.__name__}: {exc}"[:500]
            job.worker_id = None
            job.lease_expires_at = None
            if terminal:
                job.status = "failed"
                job.completed_at = datetime.utcnow()
            else:
                job.status = "queued"
                job.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(2 ** max(attempt, 1) * 5, 900))
            db.commit()
            failed += 1
            logger.exception("Field Intelligence autonomy trigger failed (job=%s)", candidate.id)
    return {"processed": processed, "failed": failed, "worker_id": worker_id}

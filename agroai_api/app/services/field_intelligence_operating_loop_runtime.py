"""Connect Field Intelligence observations to durable operator work.

The Field Intelligence capture pipeline already produces rich observations, but
its downstream actions historically behaved like disconnected buttons. This
installer keeps the existing, proven capture and processing services intact and
adds one production invariant: every observation can own one durable operator
task whose provenance points back to the exact observation, media, and evidence.

The repository uses small install_* integrations for cross-cutting product
contracts. Keeping this integration here avoids importing the heavy Field
Intelligence frontend into the portal shell and keeps the change server-side,
tenant-scoped, and transactionally durable.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

from fastapi import HTTPException, status

from app.models.field_intelligence import FieldObservation, FieldObservationAsset
from app.models.operational_records import IngestionJob

logger = logging.getLogger(__name__)

_INSTALL_MARKER = "_agroai_field_intelligence_operating_loop_installed"


def _text_items(values: Iterable[Any], *, limit: int = 12) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").replace("\x00", " ").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text[:500])
        if len(output) >= limit:
            break
    return output


def _priority_from_severity(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"critical", "urgent", "high", "severe"}:
        return "high"
    if normalized in {"medium", "moderate", "needs_review"}:
        return "medium"
    return "low"


def install_field_intelligence_operating_loop() -> None:
    """Install the observation-to-task contract exactly once per process."""
    from app.services import field_intelligence as field_service
    from app.services import field_operating_loop as operating_loop

    if getattr(field_service, _INSTALL_MARKER, False):
        return

    original_task_from_job = operating_loop._task_from_job

    def task_from_job_with_observation(job: IngestionJob) -> dict[str, Any]:
        task = original_task_from_job(job)
        payload = operating_loop.sanitize_public(job.input_json or {})
        task.update(
            {
                "source_observation_id": payload.get("source_observation_id"),
                "source_evidence_ids": list(payload.get("source_evidence_ids") or []),
                "source_asset_ids": list(payload.get("source_asset_ids") or []),
            }
        )
        return task

    setattr(task_from_job_with_observation, "__agroai_operating_loop__", True)
    operating_loop._task_from_job = task_from_job_with_observation

    def create_task_from_observation(
        db: Any,
        ctx: Any,
        observation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Resolve through the canonical service first so tenant and existence
        # boundaries remain identical to every other Field Intelligence route.
        resolved = field_service.get_observation(db, ctx, observation_id)
        field_service.authorize_workspace_action(
            db,
            ctx,
            resolved.workspace_id,
            write=True,
        )
        organization_id = field_service.require_org(ctx)

        # Lock the observation while checking and writing task_ids_json. This
        # makes double taps and slow mobile retries converge on one task.
        observation = (
            db.query(FieldObservation)
            .filter(
                FieldObservation.id == resolved.id,
                FieldObservation.tenant_id == resolved.tenant_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if observation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")

        existing_ids = [str(value) for value in (observation.task_ids_json or []) if value]
        if existing_ids:
            existing_job = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.tenant_id == organization_id,
                    IngestionJob.job_type == operating_loop.TASK_JOB_TYPE,
                    IngestionJob.id.in_(existing_ids),
                )
                .order_by(IngestionJob.created_at.asc())
                .first()
            )
            if existing_job is not None:
                task = operating_loop._task_from_job(existing_job)
                task["already_existed"] = True
                return task

        # Field Intelligence permits observations without an explicit workspace.
        # The canonical resolver maps those records to the organization's normal
        # default workspace, exactly as the original task path did.
        workspace = field_service.resolve_workspace(
            db,
            organization_id,
            observation.workspace_id,
        )
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        task_workspace_id = workspace.id

        structured = dict(observation.structured_json or {})
        vision = dict(structured.get("vision") or {})
        correlation = dict(observation.correlation_json or {})
        recommendation = str(
            observation.recommended_action
            or vision.get("recommended_follow_up")
            or correlation.get("recommended_next_action")
            or ""
        ).strip()
        summary = str(
            observation.summary
            or observation.corrected_transcript
            or observation.transcript
            or "Field observation"
        ).strip()

        instructions = _text_items(payload.get("instructions") or [])
        if not instructions:
            candidates: list[Any] = [recommendation]
            for hypothesis in vision.get("hypotheses") or []:
                if isinstance(hypothesis, dict):
                    candidates.append(hypothesis.get("verification"))
            instructions = _text_items(candidates)
        if not instructions:
            instructions = ["Review the linked observation and confirm the next accountable action."]

        evidence_required = _text_items(payload.get("evidence_required") or [])
        if not evidence_required:
            candidates = list(structured.get("evidence_requirements") or [])
            candidates.extend(observation.uncertain_fields_json or [])
            candidates.extend(vision.get("uncertainties") or [])
            for hypothesis in vision.get("hypotheses") or []:
                if isinstance(hypothesis, dict):
                    candidates.append(hypothesis.get("verification"))
            evidence_required = _text_items(candidates)

        source_asset_ids = [
            row.id
            for row in (
                db.query(FieldObservationAsset)
                .filter(
                    FieldObservationAsset.tenant_id == observation.tenant_id,
                    FieldObservationAsset.observation_id == observation.id,
                    FieldObservationAsset.status == "stored",
                )
                .all()
            )
        ]
        source_evidence_ids = [
            str(value) for value in (observation.evidence_ids_json or []) if value
        ]

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        title = str(
            payload.get("title")
            or recommendation
            or summary
            or "Field observation follow-up"
        )[:120]
        why = str(
            payload.get("why")
            or f"Field Intelligence observation {observation.id[:8]} requires follow-through: {summary}"
        )[:8000]
        task_payload = {
            "title": title,
            "field": observation.field_name,
            "block": observation.block_name,
            "assigned_to": payload.get("assigned_to"),
            "priority": payload.get("priority") or _priority_from_severity(observation.severity),
            "why": why,
            "instructions": instructions,
            "evidence_required": evidence_required,
            "source_exception_id": None,
            "source_decision_id": None,
            "source_observation_id": observation.id,
            "source_evidence_ids": source_evidence_ids,
            "source_asset_ids": source_asset_ids,
            "created_from": "field_intelligence",
            "customer_safe": True,
            "workspace_id": task_workspace_id,
        }
        job = IngestionJob(
            id=task_id,
            tenant_id=organization_id,
            workspace_id=task_workspace_id,
            job_type=operating_loop.TASK_JOB_TYPE,
            status="open",
            input_json=task_payload,
            output_json={"source": "field_intelligence", "observation_id": observation.id},
        )
        db.add(job)
        observation.task_ids_json = [task_id]

        audit = getattr(field_service, "_audit", None)
        if callable(audit):
            audit(
                observation,
                "task_created",
                actor=ctx.user.id,
                details={"task_id": task_id, "source": "field_intelligence"},
            )

        db.commit()
        db.refresh(job)
        task = operating_loop._task_from_job(job)
        task["already_existed"] = False

        try:
            from app.services.field_intelligence_metrics import tasks_created

            tasks_created.inc()
        except Exception:  # Metrics must never roll back customer work.
            logger.debug("Field Intelligence task metric unavailable", exc_info=True)
        return task

    setattr(create_task_from_observation, "__agroai_operating_loop__", True)
    field_service.create_task_from_observation = create_task_from_observation
    setattr(field_service, _INSTALL_MARKER, True)

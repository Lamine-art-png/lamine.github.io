"""Connect Field Intelligence observations to durable operator work.

The Field Intelligence capture pipeline already produces rich observations, but
its downstream actions historically behaved like disconnected buttons. This
installer keeps the existing, proven capture and processing services intact and
adds one production invariant: every observation can own one durable operator
task whose provenance points back to the exact observation, media, and evidence.
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


def _summary_is_invalid(value: Any) -> bool:
    text = str(value or "").strip()
    lowered = text.casefold()
    return (
        not text
        or "[object object]" in lowered
        or lowered in {"{}", "[]", "null", "undefined"}
        or (text.startswith("{") and text.endswith("}"))
    )


def _repair_observation_summary(observation: FieldObservation | None) -> FieldObservation | None:
    """Keep malformed model payloads out of every customer-facing summary.

    A historical model response was stringified by a browser-facing path as
    ``[object Object]``. Existing rows self-heal on read, and new extraction
    results are repaired before they can be persisted or used to create tasks.
    """
    if observation is None or not _summary_is_invalid(observation.summary):
        return observation
    structured = dict(observation.structured_json or {})
    vision = structured.get("vision") if isinstance(structured.get("vision"), dict) else {}
    candidates = [
        observation.corrected_transcript,
        observation.transcript,
        structured.get("summary"),
        vision.get("summary") if isinstance(vision, dict) else None,
        observation.recommended_action,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() and not _summary_is_invalid(candidate):
            observation.summary = candidate.strip()[:4000]
            return observation
    observation.summary = "Field observation awaiting analysis."
    return observation


def install_field_intelligence_operating_loop() -> None:
    """Install the observation-to-task contract exactly once per process."""
    from app.services import field_intelligence as field_service
    from app.services import field_operating_loop as operating_loop

    if getattr(field_service, _INSTALL_MARKER, False):
        return

    # Repair both historical rows at read time and future malformed model
    # summaries before they reach persistence. These wrappers preserve the
    # canonical tenant/workspace authorization functions underneath them.
    original_get_observation = field_service.get_observation
    original_list_observations = field_service.list_observations
    original_extract_observation = field_service.extract_observation

    def get_observation_with_valid_summary(db: Any, ctx: Any, observation_id: str):
        return _repair_observation_summary(original_get_observation(db, ctx, observation_id))

    def list_observations_with_valid_summaries(db: Any, ctx: Any, filters: dict):
        rows, total = original_list_observations(db, ctx, filters)
        for row in rows:
            _repair_observation_summary(row)
        return rows, total

    def extract_observation_with_valid_summary(*args: Any, **kwargs: Any):
        extraction = original_extract_observation(*args, **kwargs)
        summary = getattr(extraction, "summary", "")
        if _summary_is_invalid(summary):
            source_text = str(args[0] if args else kwargs.get("text") or "").strip()
            extraction.summary = source_text[:280] if source_text else "Field observation awaiting analysis."
        return extraction

    setattr(get_observation_with_valid_summary, "__agroai_summary_repair__", True)
    setattr(list_observations_with_valid_summaries, "__agroai_summary_repair__", True)
    setattr(extract_observation_with_valid_summary, "__agroai_summary_repair__", True)
    field_service.get_observation = get_observation_with_valid_summary
    field_service.list_observations = list_observations_with_valid_summaries
    field_service.extract_observation = extract_observation_with_valid_summary

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
        resolved = field_service.get_observation(db, ctx, observation_id)
        field_service.authorize_workspace_action(db, ctx, resolved.workspace_id, write=True)
        organization_id = field_service.require_org(ctx)

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
        _repair_observation_summary(observation)

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

        workspace = field_service.resolve_workspace(db, organization_id, observation.workspace_id)
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
        source_evidence_ids = [str(value) for value in (observation.evidence_ids_json or []) if value]

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        title = str(payload.get("title") or recommendation or summary or "Field observation follow-up")[:120]
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
        except Exception:
            logger.debug("Field Intelligence task metric unavailable", exc_info=True)
        return task

    setattr(create_task_from_observation, "__agroai_operating_loop__", True)
    field_service.create_task_from_observation = create_task_from_observation
    setattr(field_service, _INSTALL_MARKER, True)

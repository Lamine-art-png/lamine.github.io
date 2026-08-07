"""Connect Field Intelligence observations to durable operator work.

This installer keeps the proven capture/processing plane intact while enforcing
three product invariants at the service boundary:

* one observation owns at most one durable operator task;
* task provenance always points back to the originating observation/evidence;
* customer-facing observation text is scalar, useful text (never object dumps or
  the browser artifact ``[object Object]``).

Keeping these contracts in a small install_* integration avoids coupling the
heavy Field Intelligence frontend to API startup and makes the behavior safe to
roll back independently.
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
_BAD_TEXT = {"[object object]", "object object", "none", "null", "undefined"}


def _safe_text(value: Any, *, limit: int = 8000) -> str:
    """Return bounded human-readable text without serializing objects as junk."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.replace("\x00", " ").split()).strip()
        return "" if text.casefold() in _BAD_TEXT else text[:limit]
    if isinstance(value, dict):
        for key in ("summary", "text", "label", "message", "description", "value"):
            text = _safe_text(value.get(key), limit=limit)
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = _safe_text(item, limit=limit)
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                parts.append(text)
            if len(parts) >= 6:
                break
        return "; ".join(parts)[:limit]
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    return "" if text.casefold() in _BAD_TEXT else text[:limit]


def _text_items(values: Iterable[Any], *, limit: int = 12) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _safe_text(value, limit=500)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _priority_from_severity(value: Any) -> str:
    normalized = _safe_text(value, limit=40).lower()
    if normalized in {"critical", "urgent", "high", "severe"}:
        return "high"
    if normalized in {"medium", "moderate", "needs_review"}:
        return "medium"
    return "low"


def _clean_observation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Harden the serialized contract without changing the persisted evidence."""
    cleaned = dict(payload or {})
    raw_structured = cleaned.get("structured")
    structured = dict(raw_structured) if isinstance(raw_structured, dict) else {}
    vision = dict(structured.get("vision") or {}) if isinstance(structured.get("vision"), dict) else {}
    correlation = dict(cleaned.get("correlation") or {}) if isinstance(cleaned.get("correlation"), dict) else {}

    transcript = _safe_text(cleaned.get("corrected_transcript") or cleaned.get("transcript"), limit=8000)
    summary = (
        _safe_text(cleaned.get("summary"), limit=2000)
        or _safe_text(vision.get("summary"), limit=2000)
        or transcript[:280]
    )
    recommendation = (
        _safe_text(cleaned.get("recommended_action"), limit=2000)
        or _safe_text(vision.get("recommended_follow_up"), limit=2000)
        or _safe_text(correlation.get("recommended_next_action"), limit=2000)
    )

    cleaned["summary"] = summary or None
    cleaned["recommended_action"] = recommendation or None
    for key in ("field_name", "block_name", "crop", "event_type", "severity"):
        value = _safe_text(cleaned.get(key), limit=200)
        cleaned[key] = value or None

    if vision:
        if "summary" in vision:
            vision["summary"] = _safe_text(vision.get("summary"), limit=2000) or None
        if "recommended_follow_up" in vision:
            vision["recommended_follow_up"] = _safe_text(vision.get("recommended_follow_up"), limit=2000) or None
        structured["vision"] = vision
        cleaned["structured"] = structured

    if correlation:
        if "explanation" in correlation:
            correlation["explanation"] = _safe_text(correlation.get("explanation"), limit=2000) or None
        if "recommended_next_action" in correlation:
            correlation["recommended_next_action"] = _safe_text(
                correlation.get("recommended_next_action"), limit=2000
            ) or None
        cleaned["correlation"] = correlation

    cleaned["task_ids"] = [str(value) for value in (cleaned.get("task_ids") or []) if value]
    cleaned["evidence_ids"] = [str(value) for value in (cleaned.get("evidence_ids") or []) if value]
    return cleaned


def install_field_intelligence_operating_loop() -> None:
    """Install the observation-to-task and clean-read contracts once per process."""
    from app.services import field_intelligence as field_service
    from app.services import field_operating_loop as operating_loop

    if getattr(field_service, _INSTALL_MARKER, False):
        return

    original_serialize_observation = field_service.serialize_observation

    def serialize_observation_clean(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _clean_observation_payload(original_serialize_observation(*args, **kwargs))

    setattr(serialize_observation_clean, "__agroai_operating_loop__", True)
    field_service.serialize_observation = serialize_observation_clean

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

        structured = dict(observation.structured_json) if isinstance(observation.structured_json, dict) else {}
        vision = dict(structured.get("vision") or {}) if isinstance(structured.get("vision"), dict) else {}
        correlation = dict(observation.correlation_json) if isinstance(observation.correlation_json, dict) else {}
        recommendation = (
            _safe_text(observation.recommended_action, limit=2000)
            or _safe_text(vision.get("recommended_follow_up"), limit=2000)
            or _safe_text(correlation.get("recommended_next_action"), limit=2000)
        )
        summary = (
            _safe_text(observation.summary, limit=2000)
            or _safe_text(vision.get("summary"), limit=2000)
            or _safe_text(observation.corrected_transcript or observation.transcript, limit=2000)
            or "Field observation"
        )

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
        title = (
            _safe_text(payload.get("title"), limit=120)
            or recommendation[:120]
            or summary[:120]
            or "Field observation follow-up"
        )
        why = (
            _safe_text(payload.get("why"), limit=8000)
            or f"Field Intelligence observation {observation.id[:8]} requires follow-through: {summary}"
        )[:8000]
        task_payload = {
            "title": title,
            "field": _safe_text(observation.field_name, limit=200) or None,
            "block": _safe_text(observation.block_name, limit=200) or None,
            "assigned_to": _safe_text(payload.get("assigned_to"), limit=200) or None,
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

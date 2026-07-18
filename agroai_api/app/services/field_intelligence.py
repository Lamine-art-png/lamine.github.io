"""Field Intelligence orchestration.

Ties together capture sessions, durable assets, transcription, structured
extraction and AGRO-AI correlation into tenant-scoped observations. Idempotent
by construction so an offline client can replay safely.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.models.field_intelligence import (
    FieldCaptureSession,
    FieldObservation,
    FieldObservationAsset,
    FieldObservationProcessingRun,
)
from app.models.saas import Workspace
from app.services.field_observation_correlation import correlate_observation
from app.services.field_observation_extraction import extract_observation
from app.services.field_transcription import transcribe_capture

NEEDS_REVIEW_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# Context / scoping helpers
# ---------------------------------------------------------------------------

def require_org(ctx: AuthContext) -> str:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization.id


def resolve_workspace(db: Session, organization_id: str, workspace_id: str | None) -> Workspace | None:
    """Resolve a workspace strictly within the caller's organization.

    A workspace id from the request body is never trusted beyond this scoped
    lookup — it must belong to the authenticated organization.
    """
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return query.order_by(Workspace.created_at.asc()).first()


def _audit(observation: FieldObservation, action: str, *, actor: str | None, details: dict | None = None) -> None:
    events = list(observation.audit_json or [])
    events.append(
        {
            "action": action,
            "actor": actor,
            "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "details": details or {},
        }
    )
    observation.audit_json = events


def _record_run(
    db: Session,
    observation: FieldObservation,
    *,
    stage: str,
    provider: str | None,
    stage_status: str,
    model: str | None = None,
    language: str | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    output: dict | None = None,
) -> None:
    run = FieldObservationProcessingRun(
        id=str(uuid.uuid4()),
        tenant_id=observation.tenant_id,
        workspace_id=observation.workspace_id,
        observation_id=observation.id,
        capture_session_id=observation.capture_session_id,
        stage=stage,
        provider=provider,
        model=model,
        language=language,
        status=stage_status,
        latency_ms=latency_ms,
        error=error,
        input_json={},
        output_json=output or {},
        completed_at=datetime.utcnow(),
    )
    db.add(run)


# ---------------------------------------------------------------------------
# Capture lifecycle
# ---------------------------------------------------------------------------

def initiate_capture(db: Session, ctx: AuthContext, payload: dict) -> FieldCaptureSession:
    """Create (or idempotently return) a capture session."""
    organization_id = require_org(ctx)
    workspace = resolve_workspace(db, organization_id, payload.get("workspace_id"))
    workspace_id = workspace.id if workspace else None

    client_capture_id = str(payload.get("client_capture_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or client_capture_id or "").strip()
    if not client_capture_id or not idempotency_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="client_capture_id and idempotency_key are required")

    existing = (
        db.query(FieldCaptureSession)
        .filter(FieldCaptureSession.tenant_id == organization_id)
        .filter(
            (FieldCaptureSession.idempotency_key == idempotency_key)
            | (FieldCaptureSession.client_capture_id == client_capture_id)
        )
        .first()
    )
    if existing:
        return existing

    session = FieldCaptureSession(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=workspace_id,
        user_id=ctx.user.id,
        client_capture_id=client_capture_id,
        idempotency_key=idempotency_key,
        capture_source=payload.get("capture_source") or "typed",
        status="received",
        note_text=payload.get("note_text"),
        transcript_preview=payload.get("transcript_preview"),
        field_id=payload.get("field_id"),
        field_name=payload.get("field_name"),
        block_id=payload.get("block_id"),
        block_name=payload.get("block_name"),
        crop=payload.get("crop"),
        event_type=payload.get("event_type"),
        severity=payload.get("severity"),
        assignee=payload.get("assignee"),
        occurred_at=_parse_dt(payload.get("occurred_at")),
        latitude=_as_float(payload.get("latitude")),
        longitude=_as_float(payload.get("longitude")),
        location_accuracy_m=_as_float(payload.get("location_accuracy_m")),
        asset_manifest_json=payload.get("asset_manifest") or [],
        metadata_json=payload.get("metadata") or {},
        client_created_at=_parse_dt(payload.get("client_created_at")),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def complete_capture(db: Session, ctx: AuthContext, capture_ref: str, payload: dict | None = None) -> FieldObservation:
    """Run the pipeline for a capture and produce a durable observation.

    Idempotent: replaying complete for an already-completed capture returns the
    existing observation instead of creating a duplicate.
    """
    payload = payload or {}
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)

    if session.observation_id:
        observation = db.get(FieldObservation, session.observation_id)
        if observation:
            return observation

    session.status = "processing"
    corrected = payload.get("corrected_transcript")

    # --- Transcription (or truthful fallback) ---
    audio_ref = _first_audio_ref(session.asset_manifest_json)
    tr = transcribe_capture(
        audio_ref=audio_ref,
        language=payload.get("language") or "en",
        note_text=session.note_text,
    )
    transcript = tr.transcript if tr.status in {"completed", "skipped"} else None

    # --- Build observation shell so runs can attach to it ---
    observation = FieldObservation(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=session.workspace_id,
        user_id=session.user_id or ctx.user.id,
        capture_session_id=session.id,
        field_id=session.field_id,
        field_name=session.field_name,
        block_id=session.block_id,
        block_name=session.block_name,
        crop=session.crop,
        event_type=session.event_type,
        severity=session.severity,
        status="processing",
        occurred_at=session.occurred_at or session.created_at,
        observed_at=datetime.utcnow(),
        latitude=session.latitude,
        longitude=session.longitude,
        location_accuracy_m=session.location_accuracy_m,
        transcript=transcript,
        corrected_transcript=corrected,
        audit_json=[],
    )
    db.add(observation)
    db.flush()  # assign id for processing-run FKs

    _audit(observation, "capture_created", actor=ctx.user.id, details={"capture_id": session.id})
    _record_run(
        db, observation, stage="transcription", provider=tr.provider, stage_status=tr.status,
        model=tr.model, language=tr.language, latency_ms=tr.latency_ms, error=tr.error,
        output={"status": tr.status, "has_transcript": bool(tr.transcript)},
    )
    _audit(
        observation,
        "transcription_completed" if tr.succeeded else "transcription_failed",
        actor="system",
        details={"provider": tr.provider, "status": tr.status, "error": tr.error},
    )

    # --- Extraction ---
    source_text = corrected or transcript or session.note_text or ""
    extraction = extract_observation(
        source_text,
        field_hint=session.field_name,
        block_hint=session.block_name,
        crop_hint=session.crop,
        event_type_hint=session.event_type,
        occurred_at=session.occurred_at,
    )
    extraction_dict = extraction.model_dump(mode="json")
    observation.structured_json = extraction_dict
    observation.extraction_schema_version = extraction.schema_version
    observation.confidence = extraction.confidence
    observation.uncertain_fields_json = extraction.uncertain_fields
    observation.summary = extraction.summary or (source_text[:280] if source_text else None)
    observation.recommended_action = extraction.recommended_follow_up
    observation.event_type = observation.event_type or extraction.event_type
    observation.severity = observation.severity or extraction.severity
    observation.model_provider = "deterministic"
    observation.model_name = extraction.method
    observation.search_text = _search_text(observation, source_text)
    _record_run(
        db, observation, stage="extraction", provider="deterministic", stage_status="completed",
        model=extraction.method, output={"confidence": extraction.confidence, "uncertain": extraction.uncertain_fields},
    )
    _audit(observation, "extraction_completed", actor="system", details={"confidence": extraction.confidence})

    # --- Correlation ---
    correlation = correlate_observation(db, observation)
    observation.correlation_json = correlation
    observation.evidence_ids_json = correlation.get("relevant_evidence_ids", [])
    observation.provenance_json = {
        "extraction_schema_version": extraction.schema_version,
        "extraction_method": extraction.method,
        "transcription_provider": tr.provider,
        "transcription_status": tr.status,
        "correlation_schema_version": correlation.get("schema_version"),
    }
    if not observation.recommended_action:
        observation.recommended_action = correlation.get("recommended_next_action")
    _record_run(
        db, observation, stage="correlation", provider="agroai", stage_status="completed",
        output={"evidence_count": len(correlation.get("relevant_evidence_ids", []))},
    )
    _audit(observation, "correlation_completed", actor="system", details={
        "evidence_count": len(correlation.get("relevant_evidence_ids", [])),
    })

    observation.status = "needs_review" if extraction.confidence < NEEDS_REVIEW_CONFIDENCE else "completed"

    # Link durable assets registered during this capture to the observation.
    (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .update({FieldObservationAsset.observation_id: observation.id})
    )

    session.status = "completed"
    session.observation_id = observation.id
    session.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(observation)
    return observation


def sync_batch(db: Session, ctx: AuthContext, items: Iterable[dict]) -> dict:
    """Process a batch of offline captures with per-item, partial-success results."""
    results: list[dict] = []
    accepted = 0
    failed = 0
    for item in items:
        client_capture_id = item.get("client_capture_id")
        try:
            session = initiate_capture(db, ctx, item)
            observation = complete_capture(db, ctx, session.id, item)
            accepted += 1
            results.append(
                {
                    "client_capture_id": client_capture_id,
                    "status": "accepted",
                    "server_capture_id": session.id,
                    "observation_id": observation.id,
                    "observation_status": observation.status,
                }
            )
        except HTTPException as exc:  # keep failed items — never lose them
            db.rollback()
            failed += 1
            results.append(
                {
                    "client_capture_id": client_capture_id,
                    "status": "failed",
                    "error": str(exc.detail),
                    "http_status": exc.status_code,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface, do not hide
            db.rollback()
            failed += 1
            results.append(
                {
                    "client_capture_id": client_capture_id,
                    "status": "failed",
                    "error": exc.__class__.__name__,
                }
            )
    return {"accepted": accepted, "failed": failed, "total": accepted + failed, "results": results}


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def register_asset(
    db: Session,
    ctx: AuthContext,
    capture_ref: str,
    *,
    client_asset_id: str,
    kind: str,
    content_type: str | None,
    filename: str | None,
    content_sha256: str | None,
    size_bytes: int | None,
    duration_seconds: float | None,
    object_ref: str | None,
    storage_backend: str,
) -> FieldObservationAsset:
    """Register (idempotently) a durable asset reference for a capture."""
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)

    existing = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.client_asset_id == client_asset_id)
        .first()
    )
    if existing:
        return existing  # safe replay: dedupe on (tenant, capture, client asset)

    asset = FieldObservationAsset(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=session.workspace_id,
        capture_session_id=session.id,
        observation_id=session.observation_id,
        client_asset_id=client_asset_id,
        kind=kind,
        content_type=content_type,
        filename=filename,
        storage_backend=storage_backend,
        object_ref=object_ref,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        status="stored",
    )
    db.add(asset)
    # keep the session manifest coherent
    manifest = list(session.asset_manifest_json or [])
    manifest.append({"client_asset_id": client_asset_id, "kind": kind, "content_type": content_type})
    session.asset_manifest_json = manifest
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, ctx: AuthContext, asset_id: str) -> None:
    organization_id = require_org(ctx)
    asset = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset.status = "deleted"
    asset.deleted_at = datetime.utcnow()
    if asset.observation_id:
        observation = db.get(FieldObservation, asset.observation_id)
        if observation:
            _audit(observation, "asset_deleted", actor=ctx.user.id, details={"asset_id": asset_id})
    db.commit()


# ---------------------------------------------------------------------------
# Observation reads / mutations
# ---------------------------------------------------------------------------

def list_observations(db: Session, ctx: AuthContext, filters: dict) -> list[FieldObservation]:
    organization_id = require_org(ctx)
    query = db.query(FieldObservation).filter(FieldObservation.tenant_id == organization_id)
    workspace = resolve_workspace(db, organization_id, filters.get("workspace_id"))
    if workspace:
        query = query.filter(
            (FieldObservation.workspace_id == workspace.id) | (FieldObservation.workspace_id.is_(None))
        )
    for column, key in (
        (FieldObservation.field_id, "field_id"),
        (FieldObservation.block_id, "block_id"),
        (FieldObservation.crop, "crop"),
        (FieldObservation.event_type, "event_type"),
        (FieldObservation.severity, "severity"),
        (FieldObservation.status, "status"),
    ):
        value = filters.get(key)
        if value:
            query = query.filter(column == value)
    search = (filters.get("q") or "").strip().lower()
    if search:
        like = f"%{search}%"
        query = query.filter(FieldObservation.search_text.ilike(like))
    start = _parse_dt(filters.get("start"))
    end = _parse_dt(filters.get("end"))
    if start:
        query = query.filter(FieldObservation.occurred_at >= start)
    if end:
        query = query.filter(FieldObservation.occurred_at <= end)
    limit = min(int(filters.get("limit") or 100), 500)
    return query.order_by(FieldObservation.occurred_at.desc().nullslast()).limit(limit).all()


def get_observation(db: Session, ctx: AuthContext, observation_id: str) -> FieldObservation:
    organization_id = require_org(ctx)
    observation = (
        db.query(FieldObservation)
        .filter(FieldObservation.tenant_id == organization_id)
        .filter(FieldObservation.id == observation_id)
        .first()
    )
    if not observation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return observation


def patch_observation(db: Session, ctx: AuthContext, observation_id: str, changes: dict) -> FieldObservation:
    observation = get_observation(db, ctx, observation_id)
    corrected = changes.get("corrected_transcript")
    if corrected is not None:
        observation.corrected_transcript = corrected
        observation.search_text = _search_text(observation, corrected)
    for attr in ("field_id", "field_name", "block_id", "block_name", "crop", "event_type", "severity"):
        if attr in changes and changes[attr] is not None:
            setattr(observation, attr, changes[attr])
    if changes.get("structured") is not None:
        merged = dict(observation.structured_json or {})
        merged.update(changes["structured"])
        merged["corrected_by_user"] = True
        observation.structured_json = merged
    if changes.get("status"):
        observation.status = changes["status"]
    _audit(observation, "observation_corrected", actor=ctx.user.id, details={"fields": sorted(changes.keys())})
    db.commit()
    db.refresh(observation)
    return observation


def delete_observation(db: Session, ctx: AuthContext, observation_id: str) -> None:
    observation = get_observation(db, ctx, observation_id)
    _audit(observation, "observation_deleted", actor=ctx.user.id)
    observation.status = "deleted"
    db.commit()


def create_task_from_observation(db: Session, ctx: AuthContext, observation_id: str, payload: dict) -> dict:
    """Create an operational task, reusing the field operating loop task system."""
    from app.services.field_operating_loop import build_field_ops_context, create_task

    observation = get_observation(db, ctx, observation_id)
    organization_id = require_org(ctx)
    workspace = resolve_workspace(db, organization_id, observation.workspace_id)
    fops = build_field_ops_context(db, organization_id, workspace)
    task = create_task(
        fops,
        title=payload.get("title") or (observation.summary or "Field observation follow-up")[:120],
        field=observation.field_name,
        block=observation.block_name,
        assigned_to=payload.get("assigned_to"),
        priority=payload.get("priority") or _priority_from_severity(observation.severity),
        why=payload.get("why") or "Created from a field observation.",
        instructions=payload.get("instructions") or [],
        evidence_required=payload.get("evidence_required") or (observation.structured_json or {}).get("evidence_requirements", []),
        created_from="field_update",
    )
    task_ids = list(observation.task_ids_json or [])
    task_ids.append(task.get("id"))
    observation.task_ids_json = task_ids
    _audit(observation, "task_created", actor=ctx.user.id, details={"task_id": task.get("id")})
    db.commit()
    return task


def map_observations(db: Session, ctx: AuthContext, filters: dict) -> dict:
    rows = list_observations(db, ctx, filters)
    features = [
        {
            "observation_id": obs.id,
            "latitude": obs.latitude,
            "longitude": obs.longitude,
            "accuracy_m": obs.location_accuracy_m,
            "severity": obs.severity,
            "event_type": obs.event_type,
            "field_name": obs.field_name,
            "has_media": bool(obs.evidence_ids_json) or bool(_manifest_len(obs)),
            "occurred_at": obs.occurred_at.isoformat() if obs.occurred_at else None,
        }
        for obs in rows
        if obs.latitude is not None and obs.longitude is not None
    ]
    return {"points": features, "count": len(features), "geometry_available": bool(features)}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_capture(session: FieldCaptureSession) -> dict:
    return {
        "id": session.id,
        "client_capture_id": session.client_capture_id,
        "idempotency_key": session.idempotency_key,
        "status": session.status,
        "capture_source": session.capture_source,
        "workspace_id": session.workspace_id,
        "observation_id": session.observation_id,
        "asset_manifest": session.asset_manifest_json,
        "last_error": session.last_error,
        "created_at": _iso(session.created_at),
        "completed_at": _iso(session.completed_at),
    }


def serialize_observation(db: Session, obs: FieldObservation, *, include_runs: bool = False) -> dict:
    payload = {
        "id": obs.id,
        "workspace_id": obs.workspace_id,
        "capture_session_id": obs.capture_session_id,
        "status": obs.status,
        "field_id": obs.field_id,
        "field_name": obs.field_name,
        "block_id": obs.block_id,
        "block_name": obs.block_name,
        "crop": obs.crop,
        "event_type": obs.event_type,
        "severity": obs.severity,
        "occurred_at": _iso(obs.occurred_at),
        "observed_at": _iso(obs.observed_at),
        "location": _location(obs),
        "transcript": obs.transcript,
        "corrected_transcript": obs.corrected_transcript,
        "summary": obs.summary,
        "structured": obs.structured_json,
        "extraction_schema_version": obs.extraction_schema_version,
        "confidence": obs.confidence,
        "uncertain_fields": obs.uncertain_fields_json,
        "recommended_action": obs.recommended_action,
        "correlation": obs.correlation_json,
        "provenance": obs.provenance_json,
        "model_provider": obs.model_provider,
        "model_name": obs.model_name,
        "task_ids": obs.task_ids_json,
        "evidence_ids": obs.evidence_ids_json,
        "audit_history": obs.audit_json,
        "created_at": _iso(obs.created_at),
    }
    payload["assets"] = [
        _serialize_asset(asset)
        for asset in db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == obs.tenant_id)
        .filter(FieldObservationAsset.observation_id == obs.id)
        .filter(FieldObservationAsset.status != "deleted")
        .all()
    ]
    if include_runs:
        payload["processing_runs"] = [
            {
                "stage": run.stage,
                "provider": run.provider,
                "model": run.model,
                "status": run.status,
                "latency_ms": run.latency_ms,
                "error": run.error,
                "created_at": _iso(run.created_at),
            }
            for run in db.query(FieldObservationProcessingRun)
            .filter(FieldObservationProcessingRun.observation_id == obs.id)
            .order_by(FieldObservationProcessingRun.created_at.asc())
            .all()
        ]
    return payload


def _serialize_asset(asset: FieldObservationAsset) -> dict:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "content_type": asset.content_type,
        "filename": asset.filename,
        "size_bytes": asset.size_bytes,
        "duration_seconds": asset.duration_seconds,
        "content_sha256": asset.content_sha256,
        "status": asset.status,
        # Retrieval is via an authorized endpoint, never a public bucket URL.
        "retrieval_path": f"/v1/field-intelligence/assets/{asset.id}/content",
    }


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _load_session(db: Session, organization_id: str, capture_ref: str) -> FieldCaptureSession:
    session = (
        db.query(FieldCaptureSession)
        .filter(FieldCaptureSession.tenant_id == organization_id)
        .filter(
            (FieldCaptureSession.id == capture_ref)
            | (FieldCaptureSession.client_capture_id == capture_ref)
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture not found")
    return session


def _first_audio_ref(manifest: list | None) -> str | None:
    for item in manifest or []:
        if isinstance(item, dict) and item.get("kind") == "audio":
            return item.get("object_ref") or item.get("client_asset_id")
    return None


def _manifest_len(obs: FieldObservation) -> int:
    return 0


def _priority_from_severity(severity: str | None) -> str:
    mapping = {"critical": "high", "high": "high", "medium": "medium", "low": "low", "info": "low"}
    return mapping.get((severity or "info").lower(), "medium")


def _search_text(obs: FieldObservation, extra: str | None) -> str:
    parts = [
        obs.field_name,
        obs.block_name,
        obs.crop,
        obs.event_type,
        obs.severity,
        obs.transcript,
        obs.corrected_transcript,
        obs.summary,
        extra,
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _location(obs: FieldObservation) -> dict | None:
    if obs.latitude is None or obs.longitude is None:
        return None
    return {"latitude": obs.latitude, "longitude": obs.longitude, "accuracy_m": obs.location_accuracy_m}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None

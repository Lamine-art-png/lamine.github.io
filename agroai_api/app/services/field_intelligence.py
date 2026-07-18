"""Field Intelligence orchestration.

Ties together capture sessions, durable R2/S3 assets, transcription, structured
extraction and AGRO-AI correlation into tenant-scoped observations. Processing
is staged onto a durable job so external transcription never runs synchronously
inside the request. Idempotent by construction so an offline client can replay
safely.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext
from app.core.config import settings
from app.models.field_intelligence import (
    FieldCaptureSession,
    FieldObservation,
    FieldObservationAsset,
    FieldObservationProcessingRun,
)
from app.models.operational_records import EvidenceRecord, IngestionJob
from app.models.saas import Workspace
from app.services.field_observation_correlation import correlate_observation
from app.services.field_observation_extraction import extract_observation
from app.services.field_transcription import transcribe_audio
from app.services.object_storage import get_object_store, object_storage_configured

NEEDS_REVIEW_CONFIDENCE = 0.5
PROCESS_JOB_TYPE = "field_intelligence_process"
MAX_PROCESS_ATTEMPTS = 5
PROCESS_LEASE_SECONDS = 120
ASSET_READ_MAX_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# Context / scoping helpers
# ---------------------------------------------------------------------------

def require_org(ctx: AuthContext) -> str:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization.id


def resolve_workspace(db: Session, organization_id: str, workspace_id: str | None) -> Workspace | None:
    """Resolve a workspace strictly within the caller's organization."""
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return query.order_by(Workspace.created_at.asc()).first()


def _object_store():
    if not object_storage_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "object_storage_unavailable", "message": "Durable media storage is not configured."},
        )
    return get_object_store()


def _payload_fingerprint(payload: dict) -> str:
    canonical = {
        "note_text": (payload.get("note_text") or "").strip(),
        "capture_source": payload.get("capture_source") or "typed",
        "field_id": payload.get("field_id"),
        "field_name": payload.get("field_name"),
        "block_id": payload.get("block_id"),
        "block_name": payload.get("block_name"),
        "crop": payload.get("crop"),
        "event_type": payload.get("event_type"),
        "severity": payload.get("severity"),
        "occurred_at": str(payload.get("occurred_at") or ""),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "asset_manifest": sorted(
            [str(a.get("client_asset_id")) for a in (payload.get("asset_manifest") or []) if isinstance(a, dict)]
        ),
    }
    blob = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    """Create (or idempotently return) a capture session.

    Same idempotency key + same canonical payload returns the existing session.
    Same key + a different payload is an idempotency conflict (409).
    """
    organization_id = require_org(ctx)
    workspace = resolve_workspace(db, organization_id, payload.get("workspace_id"))
    workspace_id = workspace.id if workspace else None

    client_capture_id = str(payload.get("client_capture_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or client_capture_id or "").strip()
    if not client_capture_id or not idempotency_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="client_capture_id and idempotency_key are required")

    fingerprint = _payload_fingerprint(payload)

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
        if existing.payload_fingerprint and existing.payload_fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "idempotency_conflict",
                    "message": "The idempotency key was reused with a different payload.",
                    "capture_id": existing.id,
                },
            )
        return existing

    session = FieldCaptureSession(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=workspace_id,
        user_id=ctx.user.id,
        client_capture_id=client_capture_id,
        idempotency_key=idempotency_key,
        payload_fingerprint=fingerprint,
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
    try:
        db.commit()
    except IntegrityError:
        # Concurrent initiate with the same key: re-read the winner.
        db.rollback()
        winner = (
            db.query(FieldCaptureSession)
            .filter(FieldCaptureSession.tenant_id == organization_id)
            .filter(FieldCaptureSession.idempotency_key == idempotency_key)
            .first()
        )
        if not winner:
            raise
        if winner.payload_fingerprint and winner.payload_fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "idempotency_conflict", "message": "The idempotency key was reused with a different payload.", "capture_id": winner.id},
            )
        return winner
    db.refresh(session)
    return session


def complete_capture(db: Session, ctx: AuthContext, capture_ref: str, payload: dict | None = None) -> FieldObservation:
    """Durably stage processing and return the observation shell (HTTP 202).

    External transcription/extraction/correlation run on the durable job plane,
    not in this request. Idempotent: replay returns the existing observation.
    """
    payload = payload or {}
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)

    if session.observation_id:
        observation = db.get(FieldObservation, session.observation_id)
        if observation:
            return observation

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
        status="staged",
        occurred_at=session.occurred_at or session.created_at,
        observed_at=datetime.utcnow(),
        latitude=session.latitude,
        longitude=session.longitude,
        location_accuracy_m=session.location_accuracy_m,
        audit_json=[],
    )
    db.add(observation)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent completion: unique capture_session_id lost the race.
        db.rollback()
        session = _load_session(db, organization_id, capture_ref)
        if session.observation_id:
            existing = db.get(FieldObservation, session.observation_id)
            if existing:
                return existing
        winner = (
            db.query(FieldObservation)
            .filter(FieldObservation.capture_session_id == session.id)
            .first()
        )
        if winner:
            return winner
        raise

    _audit(observation, "capture_created", actor=ctx.user.id, details={"capture_id": session.id})

    # Link assets captured before completion to this observation so retrieval
    # gating and durable deletion follow the observation lifecycle.
    (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.observation_id.is_(None))
        .update({FieldObservationAsset.observation_id: observation.id}, synchronize_session=False)
    )

    job = IngestionJob(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=session.workspace_id,
        job_type=PROCESS_JOB_TYPE,
        status="queued",
        input_json={
            "observation_id": observation.id,
            "capture_id": session.id,
            "corrected_transcript": payload.get("corrected_transcript"),
            "language": payload.get("language") or "en",
        },
        output_json={},
        idempotency_key=f"fi-proc-{observation.id}",
        attempt_count=0,
        max_attempts=MAX_PROCESS_ATTEMPTS,
        next_attempt_at=datetime.utcnow(),
    )
    db.add(job)

    session.status = "processing"
    session.observation_id = observation.id
    db.commit()
    db.refresh(observation)
    return observation


def sync_batch(db: Session, ctx: AuthContext, items: Iterable[dict]) -> dict:
    """Stage a batch of offline captures with per-item, partial-success results.

    Each item is initiated and staged for durable processing. A failed item is
    reported but never lost, and never rolls back an already-accepted item.
    """
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
        except HTTPException as exc:
            db.rollback()
            failed += 1
            results.append(
                {
                    "client_capture_id": client_capture_id,
                    "status": "conflict" if exc.status_code == 409 else "failed",
                    "error": exc.detail if isinstance(exc.detail, str) else (exc.detail or {}),
                    "http_status": exc.status_code,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface, never hide
            db.rollback()
            failed += 1
            results.append({"client_capture_id": client_capture_id, "status": "failed", "error": exc.__class__.__name__})
    return {"accepted": accepted, "failed": failed, "total": accepted + failed, "results": results}


# ---------------------------------------------------------------------------
# Durable processing plane (leased, retried, terminal)
# ---------------------------------------------------------------------------

def _claim_job(db: Session, job: IngestionJob, worker_id: str) -> bool:
    now = datetime.utcnow()
    updated = (
        db.query(IngestionJob)
        .filter(IngestionJob.id == job.id)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .update(
            {
                IngestionJob.status: "running",
                IngestionJob.worker_id: worker_id,
                IngestionJob.attempt_count: (IngestionJob.attempt_count + 1),
                IngestionJob.lease_expires_at: now + timedelta(seconds=PROCESS_LEASE_SECONDS),
                IngestionJob.last_heartbeat_at: now,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1


def run_field_intelligence_jobs(db: Session, *, limit: int = 25, worker_id: str | None = None) -> dict:
    """Claim and process queued Field Intelligence jobs. Safe for repeated calls."""
    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    candidates = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == PROCESS_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )
    processed = 0
    failed = 0
    for job in candidates:
        if not _claim_job(db, job, worker_id):
            continue
        db.refresh(job)
        try:
            _process_observation(db, job)
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.lease_expires_at = None
            job.worker_id = None
            db.commit()
            processed += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            _fail_or_retry(db, job.id, exc)
            failed += 1
    return {"processed": processed, "failed": failed, "worker_id": worker_id}


def _fail_or_retry(db: Session, job_id: str, exc: Exception) -> None:
    job = db.get(IngestionJob, job_id)
    if not job:
        return
    terminal = int(job.attempt_count or 0) >= int(job.max_attempts or MAX_PROCESS_ATTEMPTS)
    job.error = f"{exc.__class__.__name__}: {exc}"[:500]
    job.lease_expires_at = None
    job.worker_id = None
    if terminal:
        job.status = "failed"
        observation = db.get(FieldObservation, (job.input_json or {}).get("observation_id"))
        if observation:
            observation.status = "failed"
            observation.processing_error = job.error
            _audit(observation, "processing_failed", actor="system", details={"error": job.error})
    else:
        job.status = "queued"
        job.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(2 ** int(job.attempt_count or 1) * 5, 600))
    db.commit()


def _process_observation(db: Session, job: IngestionJob) -> None:
    job_input = job.input_json or {}
    observation = db.get(FieldObservation, job_input.get("observation_id"))
    if not observation:
        return
    if observation.status in {"completed", "needs_review", "deleted"}:
        return
    observation.status = "processing"
    session = db.get(FieldCaptureSession, observation.capture_session_id)
    corrected = job_input.get("corrected_transcript") or (observation.corrected_transcript)
    language = job_input.get("language") or "en"

    # --- Transcription from verified durable audio (never client references) ---
    audio_bytes, audio_asset = _load_capture_audio(db, observation)
    tr = transcribe_audio(
        audio=audio_bytes,
        content_type=(audio_asset.content_type if audio_asset else None),
        language=language,
        note_text=(session.note_text if session else None),
    )
    transcript = tr.transcript if tr.status in {"completed", "skipped"} else None
    observation.transcript = transcript
    if corrected:
        observation.corrected_transcript = corrected
    _record_run(
        db, observation, stage="transcription", provider=tr.provider, stage_status=tr.status,
        model=tr.model, language=tr.language, latency_ms=tr.latency_ms, error=tr.error,
        output={"status": tr.status, "has_transcript": bool(tr.transcript), "audio_bytes": len(audio_bytes or b"")},
    )
    _audit(
        observation,
        "transcription_completed" if tr.succeeded else ("transcription_skipped" if tr.status == "skipped" else "transcription_failed"),
        actor="system", details={"provider": tr.provider, "status": tr.status, "error": tr.error},
    )

    # --- Extraction ---
    source_text = corrected or transcript or (session.note_text if session else "") or ""
    extraction = extract_observation(
        source_text,
        field_hint=observation.field_name,
        block_hint=observation.block_name,
        crop_hint=observation.crop,
        event_type_hint=observation.event_type,
        occurred_at=observation.occurred_at,
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
    observation.evidence_ids_json = list(correlation.get("relevant_evidence_ids", []))
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

    # --- Feed into the AGRO-AI evidence graph ---
    _link_evidence_record(db, observation)

    observation.status = "needs_review" if extraction.confidence < NEEDS_REVIEW_CONFIDENCE else "completed"
    observation.processing_error = None
    if session:
        session.status = "completed"
        session.completed_at = datetime.utcnow()
    db.flush()


def reprocess_observation(db: Session, ctx: AuthContext, observation_id: str) -> FieldObservation:
    """Re-enqueue processing for a failed/needs-review observation."""
    observation = get_observation(db, ctx, observation_id)
    organization_id = require_org(ctx)
    observation.status = "staged"
    observation.processing_error = None
    _audit(observation, "reprocess_requested", actor=ctx.user.id)
    job = IngestionJob(
        id=str(uuid.uuid4()),
        tenant_id=organization_id,
        workspace_id=observation.workspace_id,
        job_type=PROCESS_JOB_TYPE,
        status="queued",
        input_json={"observation_id": observation.id, "capture_id": observation.capture_session_id, "language": "en"},
        output_json={},
        idempotency_key=f"fi-proc-{observation.id}-{uuid.uuid4().hex[:8]}",
        attempt_count=0,
        max_attempts=MAX_PROCESS_ATTEMPTS,
        next_attempt_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(observation)
    return observation


def _link_evidence_record(db: Session, observation: FieldObservation) -> None:
    """Create/refresh an EvidenceRecord so the observation joins the graph.

    Idempotent: one evidence record per observation (keyed by metadata).
    """
    existing = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.tenant_id == observation.tenant_id)
        .filter(EvidenceRecord.evidence_type == "field_observation")
        .filter(EvidenceRecord.metadata_json["observation_id"].as_string() == observation.id)
        .first()
        if db.bind and db.bind.dialect.name == "postgresql"
        else _find_evidence_slow(db, observation)
    )
    summary = observation.summary or observation.corrected_transcript or observation.transcript or "Field observation"
    if existing:
        existing.summary = summary[:2000]
        existing.value_json = observation.structured_json or {}
        existing.confidence = observation.confidence or 0.5
        return
    record = EvidenceRecord(
        id=str(uuid.uuid4()),
        tenant_id=observation.tenant_id,
        workspace_id=observation.workspace_id,
        evidence_type="field_observation",
        field_id=observation.field_id,
        block_id=observation.block_id,
        occurred_at=observation.occurred_at,
        source_updated_at=datetime.utcnow(),
        title=(observation.field_name or "Field observation") + f" — {observation.event_type or 'observation'}",
        summary=summary[:2000],
        value_json=observation.structured_json or {},
        units=None,
        confidence=observation.confidence or 0.5,
        quality_status="usable",
        citation_label=f"Field observation {observation.id[:8]}",
        source_excerpt=(observation.corrected_transcript or observation.transcript or "")[:1000] or None,
        metadata_json={
            "observation_id": observation.id,
            "capture_session_id": observation.capture_session_id,
            "source_mode": "field_capture",
            "provenance": observation.provenance_json,
        },
    )
    db.add(record)
    db.flush()
    evidence_ids = list(observation.evidence_ids_json or [])
    evidence_ids.append(record.id)
    observation.evidence_ids_json = evidence_ids
    _audit(observation, "evidence_linked", actor="system", details={"evidence_id": record.id})


def _find_evidence_slow(db: Session, observation: FieldObservation) -> EvidenceRecord | None:
    for record in (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.tenant_id == observation.tenant_id)
        .filter(EvidenceRecord.evidence_type == "field_observation")
        .all()
    ):
        if (record.metadata_json or {}).get("observation_id") == observation.id:
            return record
    return None


# ---------------------------------------------------------------------------
# Assets (durable R2/S3)
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
    content_sha256: str,
    size_bytes: int,
    duration_seconds: float | None,
    spool_path: str,
) -> FieldObservationAsset:
    """Durably store an asset in R2/S3 and register its authorized reference.

    Never claims durability until the object store verifies the upload. Safe
    replay and same-content dedupe reuse the existing durable object.
    """
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)

    existing = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.client_asset_id == client_asset_id)
        .first()
    )
    if existing and existing.status != "deleted":
        return existing  # safe replay: no re-upload, spool cleaned by caller

    # Same-content dedupe within the capture reuses the durable object.
    twin = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.content_sha256 == content_sha256)
        .filter(FieldObservationAsset.status == "stored")
        .first()
    )
    if twin:
        object_ref = twin.object_ref
        backend = twin.storage_backend
    else:
        store = _object_store()
        stored = store.put_path(
            spool_path,
            tenant_id=organization_id,
            connection_id=session.id,  # capture session is the storage scope
            filename=filename or f"{client_asset_id}",
            content_type=content_type,
            expected_sha256=content_sha256,
            expected_size=size_bytes,
        )
        object_ref = stored.uri
        backend = "s3"

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
        storage_backend=backend,
        object_ref=object_ref,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        status="stored",
    )
    db.add(asset)
    manifest = list(session.asset_manifest_json or [])
    if not any(isinstance(m, dict) and m.get("client_asset_id") == client_asset_id for m in manifest):
        manifest.append({"client_asset_id": client_asset_id, "kind": kind, "content_type": content_type})
        session.asset_manifest_json = manifest
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == organization_id)
            .filter(FieldObservationAsset.capture_session_id == session.id)
            .filter(FieldObservationAsset.client_asset_id == client_asset_id)
            .first()
        )
        if winner:
            return winner
        raise
    db.refresh(asset)
    return asset


def read_asset_bytes(db: Session, ctx: AuthContext, asset_id: str) -> tuple[FieldObservationAsset, bytes]:
    organization_id = require_org(ctx)
    asset = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.id == asset_id)
        .first()
    )
    if not asset or asset.status != "stored":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # A deleted observation immediately disables retrieval of its assets.
    if asset.observation_id:
        observation = db.get(FieldObservation, asset.observation_id)
        if observation and observation.status == "deleted":
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Asset no longer available")
    store = _object_store()
    data = store.read_bytes(
        asset.object_ref,
        max_bytes=ASSET_READ_MAX_BYTES,
        tenant_id=organization_id,
        connection_id=asset.capture_session_id,
    )
    return asset, data


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
    _schedule_asset_deletion(db, asset)
    if asset.observation_id:
        observation = db.get(FieldObservation, asset.observation_id)
        if observation:
            _audit(observation, "asset_deleted", actor=ctx.user.id, details={"asset_id": asset_id})
    db.commit()


def _schedule_asset_deletion(db: Session, asset: FieldObservationAsset) -> None:
    """Mark pending deletion, then attempt durable object removal."""
    asset.status = "pending_deletion"
    asset.deleted_at = datetime.utcnow()
    if not asset.object_ref or asset.storage_backend != "s3":
        asset.status = "deleted"
        return
    # Only remove the durable object when no other stored asset references it.
    shared = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == asset.tenant_id)
        .filter(FieldObservationAsset.object_ref == asset.object_ref)
        .filter(FieldObservationAsset.id != asset.id)
        .filter(FieldObservationAsset.status == "stored")
        .count()
    )
    try:
        if shared == 0 and object_storage_configured():
            get_object_store().delete(
                asset.object_ref, tenant_id=asset.tenant_id, connection_id=asset.capture_session_id
            )
        asset.status = "deleted"
        asset.object_deleted_at = datetime.utcnow()
    except Exception:  # noqa: BLE001 - keep pending for retry, never lose the row
        asset.delete_attempts = int(asset.delete_attempts or 0) + 1


def run_pending_asset_deletions(db: Session, *, limit: int = 50) -> int:
    pending = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.status == "pending_deletion")
        .limit(limit)
        .all()
    )
    done = 0
    for asset in pending:
        _schedule_asset_deletion(db, asset)
        if asset.status == "deleted":
            done += 1
    db.commit()
    return done


# ---------------------------------------------------------------------------
# Observation reads / mutations
# ---------------------------------------------------------------------------

def list_observations(db: Session, ctx: AuthContext, filters: dict) -> tuple[list[FieldObservation], int]:
    organization_id = require_org(ctx)
    query = db.query(FieldObservation).filter(FieldObservation.tenant_id == organization_id)
    query = query.filter(FieldObservation.status != "deleted")
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
        (FieldObservation.user_id, "author"),
    ):
        value = filters.get(key)
        if value:
            query = query.filter(column == value)
    search = (filters.get("q") or "").strip().lower()
    if search:
        query = query.filter(FieldObservation.search_text.ilike(f"%{search}%"))
    start = _parse_dt(filters.get("start"))
    end = _parse_dt(filters.get("end"))
    if start:
        query = query.filter(FieldObservation.occurred_at >= start)
    if end:
        query = query.filter(FieldObservation.occurred_at <= end)
    total = query.count()
    limit = min(int(filters.get("limit") or 100), 500)
    offset = max(int(filters.get("offset") or 0), 0)
    rows = (
        query.order_by(FieldObservation.occurred_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def get_observation(db: Session, ctx: AuthContext, observation_id: str) -> FieldObservation:
    organization_id = require_org(ctx)
    observation = (
        db.query(FieldObservation)
        .filter(FieldObservation.tenant_id == organization_id)
        .filter(FieldObservation.id == observation_id)
        .first()
    )
    if not observation or observation.status == "deleted":
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
    # keep the linked evidence in sync
    _refresh_linked_evidence(db, observation)
    db.commit()
    db.refresh(observation)
    return observation


def _refresh_linked_evidence(db: Session, observation: FieldObservation) -> None:
    record = _find_evidence_slow(db, observation)
    if record:
        record.summary = (observation.summary or observation.corrected_transcript or observation.transcript or "Field observation")[:2000]
        record.value_json = observation.structured_json or {}


def delete_observation(db: Session, ctx: AuthContext, observation_id: str) -> None:
    observation = get_observation(db, ctx, observation_id)
    _audit(observation, "observation_deleted", actor=ctx.user.id)
    observation.status = "deleted"
    # disable + schedule durable deletion of every linked asset
    for asset in (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
        .filter(FieldObservationAsset.observation_id == observation.id)
        .filter(FieldObservationAsset.status == "stored")
        .all()
    ):
        _schedule_asset_deletion(db, asset)
    # remove linked evidence from the graph
    evidence = _find_evidence_slow(db, observation)
    if evidence:
        db.delete(evidence)
    db.commit()


def create_task_from_observation(db: Session, ctx: AuthContext, observation_id: str, payload: dict) -> dict:
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
    rows, _total = list_observations(db, ctx, {**filters, "limit": 500})
    features = [
        {
            "observation_id": obs.id,
            "latitude": obs.latitude,
            "longitude": obs.longitude,
            "accuracy_m": obs.location_accuracy_m,
            "severity": obs.severity,
            "event_type": obs.event_type,
            "field_name": obs.field_name,
            "has_media": bool(obs.evidence_ids_json),
            "occurred_at": obs.occurred_at.isoformat() if obs.occurred_at else None,
        }
        for obs in rows
        if _valid_coord(obs.latitude, obs.longitude)
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
        "processing_error": obs.processing_error,
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
        .filter(FieldObservationAsset.status == "stored")
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


def _load_capture_audio(db: Session, observation: FieldObservation) -> tuple[bytes | None, FieldObservationAsset | None]:
    """Return durable audio bytes for a capture from verified asset rows only."""
    asset = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == observation.tenant_id)
        .filter(FieldObservationAsset.capture_session_id == observation.capture_session_id)
        .filter(FieldObservationAsset.kind == "audio")
        .filter(FieldObservationAsset.status == "stored")
        .order_by(FieldObservationAsset.created_at.asc())
        .first()
    )
    if not asset or not asset.object_ref:
        return None, None
    store = get_object_store()
    data = store.read_bytes(
        asset.object_ref,
        max_bytes=ASSET_READ_MAX_BYTES,
        tenant_id=observation.tenant_id,
        connection_id=observation.capture_session_id,
    )
    return data, asset


def _priority_from_severity(severity: str | None) -> str:
    mapping = {"critical": "high", "high": "high", "medium": "medium", "low": "low", "info": "low"}
    return mapping.get((severity or "info").lower(), "medium")


def _search_text(obs: FieldObservation, extra: str | None) -> str:
    parts = [
        obs.field_name, obs.block_name, obs.crop, obs.event_type, obs.severity,
        obs.transcript, obs.corrected_transcript, obs.summary, extra,
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _location(obs: FieldObservation) -> dict | None:
    if not _valid_coord(obs.latitude, obs.longitude):
        return None
    return {"latitude": obs.latitude, "longitude": obs.longitude, "accuracy_m": obs.location_accuracy_m}


def _valid_coord(lat: Any, lon: Any) -> bool:
    try:
        return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
    except (TypeError, ValueError):
        return False


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

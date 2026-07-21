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
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.api.deps import AuthContext, require_workspace_access
from app.core.config import settings
from app.models.field_intelligence import (
    FieldCaptureSession,
    FieldObservation,
    FieldObservationAsset,
    FieldObservationAuditEvent,
    FieldObservationProcessingRun,
    FieldStorageReservation,
)
from app.models.operational_records import EvidenceRecord, IngestionJob
from app.models.saas import Workspace
from app.services.field_observation_correlation import correlate_observation
from app.services.field_observation_extraction import extract_observation
from app.services.field_transcription import (
    RetryableTranscriptionError,
    classify_transcription_error,
    transcribe_audio,
)
from app.services.object_storage import get_object_store, object_storage_configured

logger = logging.getLogger(__name__)

NEEDS_REVIEW_CONFIDENCE = 0.5
PROCESS_JOB_TYPE = "field_intelligence_process"
ASSET_DELETE_JOB_TYPE = "field_intelligence_asset_delete"
ORPHAN_CLEANUP_JOB_TYPE = "field_intelligence_orphan_cleanup"
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


# Roles allowed to create/modify field intelligence data. ``viewer`` is
# read-only; destructive actions additionally require owner/admin.
WRITE_ROLES = {"owner", "admin", "operator"}


def authorize_workspace_action(
    db: Session,
    ctx: AuthContext,
    workspace_id: str | None,
    *,
    write: bool = False,
    destructive: bool = False,
) -> None:
    """Enforce the platform's workspace-access authorization on a specific record.

    Applied on every direct-ID route (captures, observations, assets, patch,
    delete, reprocess, task creation) — never only on list-query filtering.
    Denial of a foreign workspace is a 404 so existence is not leaked.
    """
    from app.services.entitlements import require_owner_or_admin

    organization_id = require_org(ctx)
    membership = getattr(ctx, "membership", None)
    if workspace_id:
        workspace, membership = require_workspace_access(workspace_id, ctx.user, db)
        if workspace.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    role = str(getattr(membership, "role", None) or "")
    if destructive:
        require_owner_or_admin(role)
    elif write and role not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "write_role_required", "message": "Your role cannot modify field intelligence data."},
        )


def require_capability(db: Session, ctx: AuthContext, feature_key: str):
    """Server-side commercial boundary — frontend locks are UX only."""
    from app.services.commercial_control import require_feature

    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return require_feature(db, ctx.organization, feature_key)


def _enforce_voice_note_quota(db: Session, ctx: AuthContext) -> None:
    """Plan-scoped monthly voice-note cap (deliberate commercial packaging).

    Unlimited when the plan has no quota value. New voice captures beyond the
    cap are refused with the standard commercial 402; replays of an existing
    idempotency key never reach this check.
    """
    from app.services.quota import committed_usage, quota_limit

    organization = ctx.organization
    if organization is None:
        return
    limit = quota_limit(db, organization, "field_voice_note")
    if limit is None:
        return
    used = committed_usage(db, organization, "field_voice_note")
    if used >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "voice_note_quota_exceeded",
                "metric": "field_intelligence.voice_notes.monthly",
                "limit": limit,
                "used": used,
                "message": "The monthly voice-note allowance for this plan is used up.",
            },
        )


def _record_voice_note_usage(db: Session, ctx: AuthContext) -> None:
    from app.services.quota import record_usage

    if ctx.organization is None:
        return
    try:
        record_usage(db, ctx.organization, "field_voice_note", quantity=1,
                     metadata={"surface": "field_intelligence"})
    except TypeError:
        # Older record_usage signatures; usage metering must never break capture.
        try:
            record_usage(db, ctx.organization, "field_voice_note", 1)
        except Exception:  # noqa: BLE001
            logger.warning("voice-note usage recording unavailable")
    except Exception:  # noqa: BLE001
        logger.warning("voice-note usage recording failed")


def storage_quota_limit_bytes(db: Session, ctx: AuthContext) -> tuple[int, int] | None:
    """Return ``(limit_bytes, limit_mb)`` for the plan quota, or None if unlimited."""
    from app.services.commercial_control import resolve_effective_entitlements

    effective = resolve_effective_entitlements(db, ctx.organization)
    limit_mb = effective.value("quota.field_intelligence.storage_mb")
    if limit_mb is None:
        return None
    try:
        return int(limit_mb) * 1024 * 1024, int(limit_mb)
    except (TypeError, ValueError):
        return None


def physical_storage_used_bytes(db: Session, tenant_id: str) -> int:
    """Tenant media usage counted per *physical object*, not per logical row.

    Multiple logical assets that share one ``object_ref`` count once. Usage is
    released only when the physical object is actually deleted (every sharing
    row has left the stored/pending_deletion states).
    """
    live = ["stored", "pending_deletion"]
    per_object = (
        db.query(func.max(FieldObservationAsset.size_bytes).label("size_bytes"))
        .filter(FieldObservationAsset.tenant_id == tenant_id)
        .filter(FieldObservationAsset.status.in_(live))
        .filter(FieldObservationAsset.object_ref.isnot(None))
        .group_by(FieldObservationAsset.object_ref)
        .subquery()
    )
    shared = db.query(func.coalesce(func.sum(per_object.c.size_bytes), 0)).scalar() or 0
    unbacked = (
        db.query(func.coalesce(func.sum(FieldObservationAsset.size_bytes), 0))
        .filter(FieldObservationAsset.tenant_id == tenant_id)
        .filter(FieldObservationAsset.status.in_(live))
        .filter(FieldObservationAsset.object_ref.is_(None))
        .scalar()
        or 0
    )
    return int(shared) + int(unbacked)


def _active_reservation_bytes(db: Session, tenant_id: str) -> int:
    total = (
        db.query(func.coalesce(func.sum(FieldStorageReservation.size_bytes), 0))
        .filter(FieldStorageReservation.tenant_id == tenant_id)
        .filter(FieldStorageReservation.expires_at > datetime.utcnow())
        .scalar()
        or 0
    )
    return int(total)


# Process-local per-tenant storage locks (SQLite / single-node). On PostgreSQL
# the transaction-scoped advisory lock is authoritative across API workers.
_STORAGE_LOCKS: dict[str, threading.Lock] = {}
_STORAGE_LOCKS_GUARD = threading.Lock()


@contextmanager
def _tenant_storage_lock(db: Session, tenant_id: str):
    """Serialize quota accounting for one tenant across concurrent uploads."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _advisory_lock_key(f"fi-storage:{tenant_id}")},
        )
        yield  # released when the surrounding transaction commits or rolls back
        return
    with _STORAGE_LOCKS_GUARD:
        lock = _STORAGE_LOCKS.setdefault(tenant_id, threading.Lock())
    with lock:
        yield


def reserve_storage(
    db: Session, ctx: AuthContext, incoming_bytes: int, *, capture_session_id: str | None = None
) -> FieldStorageReservation | None:
    """Atomically reserve quota *before* a new physical object is created.

    The check and the reservation insert commit under a per-tenant lock, so
    concurrent uploads cannot overshoot the plan quota. Returns None when the
    plan is unlimited. Raises 402 when the quota would be exceeded.
    """
    organization_id = require_org(ctx)
    limits = storage_quota_limit_bytes(db, ctx)
    if limits is None:
        return None
    limit_bytes, limit_mb = limits
    with _tenant_storage_lock(db, organization_id):
        # Expired reservations from crashed uploads never block new capacity.
        (
            db.query(FieldStorageReservation)
            .filter(FieldStorageReservation.tenant_id == organization_id)
            .filter(FieldStorageReservation.expires_at <= datetime.utcnow())
            .delete(synchronize_session=False)
        )
        used = physical_storage_used_bytes(db, organization_id)
        reserved = _active_reservation_bytes(db, organization_id)
        if used + reserved + int(incoming_bytes) > limit_bytes:
            db.rollback()
            from app.services.field_intelligence_metrics import quota_reservation_failures

            quota_reservation_failures.inc()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "storage_quota_exceeded",
                    "metric": "field_intelligence.storage_mb",
                    "limit_mb": limit_mb,
                    "used_bytes": used,
                    "message": "Field media storage quota reached for this plan.",
                },
            )
        reservation = FieldStorageReservation(
            id=str(uuid.uuid4()),
            tenant_id=organization_id,
            capture_session_id=capture_session_id,
            size_bytes=int(incoming_bytes),
            expires_at=datetime.utcnow()
            + timedelta(seconds=int(getattr(settings, "FIELD_STORAGE_RESERVATION_TTL_SECONDS", 3600))),
        )
        db.add(reservation)
        db.commit()
    return reservation


def release_storage_reservation(db: Session, reservation: FieldStorageReservation | None) -> None:
    """Best-effort release; an unreleasable reservation expires by TTL."""
    if reservation is None:
        return
    try:
        (
            db.query(FieldStorageReservation)
            .filter(FieldStorageReservation.id == reservation.id)
            .delete(synchronize_session=False)
        )
        db.commit()
    except Exception:  # noqa: BLE001 - TTL expiry is the durable fallback
        db.rollback()
        logger.warning("field-intelligence storage reservation release failed (id=%s)", reservation.id)


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


def _normalized_manifest(payload: dict) -> list:
    """Fully normalize the asset manifest (client id, kind, content type)."""
    items = []
    for asset in payload.get("asset_manifest") or []:
        if not isinstance(asset, dict):
            continue
        items.append(
            {
                "client_asset_id": str(asset.get("client_asset_id") or ""),
                "kind": str(asset.get("kind") or ""),
                "content_type": str(asset.get("content_type") or ""),
            }
        )
    return sorted(items, key=lambda a: a["client_asset_id"])


def _payload_fingerprint(payload: dict, *, workspace_id: str | None) -> str:
    """Canonical fingerprint of the *accepted* capture payload.

    Includes every field the server persists so that a replay with any material
    difference (workspace, assignee, metadata, manifest, ...) is a conflict.
    """
    canonical = {
        "workspace_id": workspace_id,
        "note_text": (payload.get("note_text") or "").strip(),
        "transcript_preview": (payload.get("transcript_preview") or "").strip(),
        "capture_source": payload.get("capture_source") or "typed",
        "field_id": payload.get("field_id"),
        "field_name": payload.get("field_name"),
        "block_id": payload.get("block_id"),
        "block_name": payload.get("block_name"),
        "crop": payload.get("crop"),
        "event_type": payload.get("event_type"),
        "severity": payload.get("severity"),
        "assignee": payload.get("assignee"),
        "occurred_at": str(payload.get("occurred_at") or ""),
        "client_created_at": str(payload.get("client_created_at") or ""),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "location_accuracy_m": payload.get("location_accuracy_m"),
        "metadata": payload.get("metadata") or {},
        "asset_manifest": _normalized_manifest(payload),
    }
    blob = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _audit(observation: FieldObservation, action: str, *, actor: str | None, details: dict | None = None) -> None:
    """Record an audit event.

    The authoritative record is an append-only row in
    ``field_observation_audit_events``; ``observation.audit_json`` is only a
    denormalized presentation cache.
    """
    now = datetime.utcnow()
    actor_type = "system" if actor == "system" else "user"
    session = object_session(observation)
    if session is not None:
        session.add(
            FieldObservationAuditEvent(
                id=str(uuid.uuid4()),
                tenant_id=observation.tenant_id,
                workspace_id=observation.workspace_id,
                observation_id=observation.id,
                capture_session_id=observation.capture_session_id,
                asset_id=(details or {}).get("asset_id"),
                action=action,
                actor=actor,
                actor_type=actor_type,
                details_json=details or {},
                created_at=now,
            )
        )
    events = list(observation.audit_json or [])
    events.append(
        {"action": action, "actor": actor, "at": now.isoformat(timespec="seconds") + "Z", "details": details or {}}
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
    attempt_count: int = 1,
) -> None:
    from app.services.field_intelligence_metrics import processing_outcomes, stage_latency, transcription_latency

    processing_outcomes.labels(stage=stage, outcome=stage_status).inc()
    if latency_ms is not None:
        stage_latency.labels(stage=stage).observe(max(latency_ms, 0) / 1000.0)
        if stage == "transcription":
            transcription_latency.labels(provider=provider or "unknown", status=stage_status).observe(
                max(latency_ms, 0) / 1000.0
            )
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
        attempt_count=attempt_count,
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
    authorize_workspace_action(db, ctx, workspace_id, write=True)
    require_capability(db, ctx, "field_intelligence.capture")
    manifest_kinds = {
        str(item.get("kind") or "")
        for item in (payload.get("asset_manifest") or [])
        if isinstance(item, dict)
    }
    is_voice_capture = payload.get("capture_source") == "voice" or bool(manifest_kinds & {"audio", "video"})
    if is_voice_capture:
        require_capability(db, ctx, "field_intelligence.voice")

    client_capture_id = str(payload.get("client_capture_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or client_capture_id or "").strip()
    if not client_capture_id or not idempotency_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="client_capture_id and idempotency_key are required")
    if len(idempotency_key) > 120:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="idempotency_key exceeds 120 characters")

    fingerprint = _payload_fingerprint(payload, workspace_id=workspace_id)

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

    if is_voice_capture:
        # Quota binds only on NEW voice captures; idempotent replays above
        # returned before ever reaching this check.
        _enforce_voice_note_quota(db, ctx)
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
        # Persist exactly what was fingerprinted — the normalized manifest.
        asset_manifest_json=_normalized_manifest(payload),
        metadata_json=payload.get("metadata") or {},
        client_created_at=_parse_dt(payload.get("client_created_at")),
    )
    db.add(session)
    try:
        db.commit()
        if is_voice_capture:
            _record_voice_note_usage(db, ctx)
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
    from app.services.field_intelligence_metrics import captures_initiated
    from app.services.field_intelligence_rollout import organization_cohort

    captures_initiated.labels(
        source=str(payload.get("capture_source") or "typed"),
        cohort=organization_cohort(db, ctx.organization),
    ).inc()
    return session


def complete_capture(db: Session, ctx: AuthContext, capture_ref: str, payload: dict | None = None) -> FieldObservation:
    """Durably stage processing and return the observation shell (HTTP 202).

    External transcription/extraction/correlation run on the durable job plane,
    not in this request. Idempotent: replay returns the existing observation.
    """
    payload = payload or {}
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)
    authorize_workspace_action(db, ctx, session.workspace_id, write=True)
    require_capability(db, ctx, "field_intelligence.capture")

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
    from app.services.field_intelligence_metrics import observations_created
    from app.services.field_intelligence_rollout import organization_cohort

    observations_created.labels(cohort=organization_cohort(db, ctx.organization)).inc()
    return observation


def sync_batch(db: Session, ctx: AuthContext, items: Iterable[dict]) -> dict:
    """Stage a batch of offline captures with per-item, partial-success results.

    Each item is initiated and staged for durable processing. A failed item is
    reported but never lost, and never rolls back an already-accepted item.
    """
    require_capability(db, ctx, "field_intelligence.offline_sync")
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
    from app.services.field_intelligence_metrics import sync_batches

    sync_batches.labels(outcome="processed").inc()
    return {"accepted": accepted, "failed": failed, "total": accepted + failed, "results": results}


# ---------------------------------------------------------------------------
# Durable processing plane (leased, retried, terminal)
# ---------------------------------------------------------------------------

class JobOwnershipLost(Exception):
    """This worker no longer owns the job lease; abandon without side effects."""


def _renew_job_lease(db: Session, job: IngestionJob) -> None:
    """Extend the running job's lease in the current transaction.

    Committed at the next stage checkpoint so a second API worker never sees an
    expired lease on a legitimately progressing job.
    """
    now = datetime.utcnow()
    job.lease_expires_at = now + timedelta(seconds=PROCESS_LEASE_SECONDS)
    job.last_heartbeat_at = now


class _JobLeaseHeartbeat:
    """Background lease renewal for long blocking stages (R2 reads, provider calls).

    Runs on its own session/connection against the same engine so renewal is
    transaction-safe and independent of the pipeline transaction. A tick that
    matches zero rows means another worker took ownership -> ``lost`` is set and
    the pipeline aborts at the next checkpoint. Transient DB errors (e.g. a
    SQLite write lock held by the pipeline) are retried on the next tick and
    never treated as lost ownership.
    """

    def __init__(self, db: Session, job_id: str, worker_id: str, *, interval_seconds: float | None = None):
        self._engine = db.get_bind()
        self._job_id = job_id
        self._worker_id = worker_id
        self._interval = interval_seconds or max(PROCESS_LEASE_SECONDS / 3.0, 0.2)
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._thread: threading.Thread | None = None

    def beat_once(self) -> None:
        try:
            with Session(bind=self._engine) as session:
                now = datetime.utcnow()
                updated = (
                    session.query(IngestionJob)
                    .filter(IngestionJob.id == self._job_id)
                    .filter(IngestionJob.worker_id == self._worker_id)
                    .filter(IngestionJob.status == "running")
                    .update(
                        {
                            IngestionJob.lease_expires_at: now + timedelta(seconds=PROCESS_LEASE_SECONDS),
                            IngestionJob.last_heartbeat_at: now,
                        },
                        synchronize_session=False,
                    )
                )
                session.commit()
            if updated == 0:
                self.lost.set()
        except Exception:  # noqa: BLE001 - transient; retry next tick
            pass

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if self.lost.is_set():
                return
            self.beat_once()

    def start(self) -> "_JobLeaseHeartbeat":
        self._thread = threading.Thread(target=self._run, name=f"fi-lease-{self._job_id[:8]}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def check(self) -> None:
        if self.lost.is_set():
            raise JobOwnershipLost(self._job_id)


def _claim_job(db: Session, job: IngestionJob, worker_id: str) -> bool:
    now = datetime.utcnow()
    if job.worker_id and job.lease_expires_at and job.lease_expires_at <= now:
        # A previous worker's lease lapsed; this claim is a stale-lease reclaim.
        from app.services.field_intelligence_metrics import stale_leases

        stale_leases.inc()
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
        heartbeat = _JobLeaseHeartbeat(db, job.id, worker_id).start()
        try:
            _process_observation(db, job, heartbeat=heartbeat)
            heartbeat.stop()
            heartbeat.check()
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.lease_expires_at = None
            job.worker_id = None
            db.commit()
            processed += 1
        except JobOwnershipLost:
            # Another worker legitimately owns the job now; leave its state alone.
            db.rollback()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            _fail_or_retry(db, job.id, exc)
            failed += 1
        finally:
            heartbeat.stop()
    return {"processed": processed, "failed": failed, "worker_id": worker_id}


def _fail_or_retry(db: Session, job_id: str, exc: Exception) -> None:
    from app.services.field_intelligence_metrics import processing_retries

    processing_retries.labels(stage="job").inc()
    """Requeue or terminally fail a job — and durably record the attempt.

    Runs after the pipeline transaction rolled back, so the attempted stage's
    processing run and audit event are re-recorded here in their own
    transaction. Provider/model/classification/latency travel on the
    exception's ``provenance`` where available.
    """
    job = db.get(IngestionJob, job_id)
    if not job:
        return
    attempt = int(job.attempt_count or 0)
    terminal = attempt >= int(job.max_attempts or MAX_PROCESS_ATTEMPTS)
    disposition = "terminal" if terminal else "retryable"
    job.error = f"{exc.__class__.__name__}: {exc}"[:500]
    job.lease_expires_at = None
    job.worker_id = None
    observation = db.get(FieldObservation, (job.input_json or {}).get("observation_id"))
    if observation is not None:
        provenance = dict(getattr(exc, "provenance", None) or {})
        stage = provenance.get("stage") or "pipeline"
        error_text = provenance.get("error") or job.error
        _record_run(
            db,
            observation,
            stage=stage,
            provider=provenance.get("provider"),
            stage_status="failed",
            model=provenance.get("model"),
            language=provenance.get("language"),
            latency_ms=provenance.get("latency_ms"),
            error=error_text,
            attempt_count=attempt,
            output={
                "attempt": attempt,
                "disposition": disposition,
                "retryable": bool(provenance.get("retryable", not terminal)),
                "http_classification": provenance.get("http_classification")
                or classify_transcription_error(error_text),
            },
        )
        _audit(
            observation,
            "processing_attempt_failed",
            actor="system",
            details={
                "stage": stage,
                "attempt": attempt,
                "disposition": disposition,
                "provider": provenance.get("provider"),
                "error": error_text,
            },
        )
    if terminal:
        job.status = "failed"
        if observation:
            observation.status = "failed"
            observation.processing_error = job.error
            _audit(observation, "processing_failed", actor="system", details={"error": job.error})
    else:
        job.status = "queued"
        job.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(2 ** int(job.attempt_count or 1) * 5, 600))
    db.commit()


def _process_observation(db: Session, job: IngestionJob, *, heartbeat: _JobLeaseHeartbeat | None = None) -> None:
    def _checkpoint() -> None:
        # Stage boundary: renew the job lease and durably commit the stage's
        # provenance so a slow later stage can never be reclaimed or lose runs.
        if heartbeat is not None:
            heartbeat.check()
        _renew_job_lease(db, job)
        db.commit()

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
    _checkpoint()  # release the pipeline write transaction before slow R2/provider I/O

    # --- Transcription from verified durable audio (never client references) ---
    audio_bytes, audio_asset = _load_capture_audio(db, observation)
    _checkpoint()
    tr = transcribe_audio(
        audio=audio_bytes,
        content_type=(audio_asset.content_type if audio_asset else None),
        language=language,
        note_text=(session.note_text if session else None),
    )
    if heartbeat is not None:
        heartbeat.check()

    # A transient provider failure (429/5xx/timeout/network) must not complete
    # the job — raise so the durable plane retries with backoff. The attempt's
    # run + audit provenance travel on the exception and are persisted by
    # ``_fail_or_retry`` after the pipeline transaction rolls back.
    if tr.status == "failed" and tr.retryable:
        raise RetryableTranscriptionError(
            tr.error or "transcription_retryable_failure",
            provenance={
                "stage": "transcription",
                "provider": tr.provider,
                "model": tr.model,
                "language": tr.language,
                "latency_ms": tr.latency_ms,
                "error": tr.error,
                "retryable": True,
                "http_classification": classify_transcription_error(tr.error),
            },
        )

    transcript = tr.transcript if tr.status in {"completed", "skipped"} else None
    observation.transcript = transcript
    if corrected:
        observation.corrected_transcript = corrected
    _record_run(
        db, observation, stage="transcription", provider=tr.provider, stage_status=tr.status,
        model=tr.model, language=tr.language, latency_ms=tr.latency_ms, error=tr.error,
        attempt_count=int(job.attempt_count or 1),
        output={"status": tr.status, "has_transcript": bool(tr.transcript), "audio_bytes": len(audio_bytes or b"")},
    )
    _audit(
        observation,
        "transcription_completed" if tr.succeeded else ("transcription_skipped" if tr.status == "skipped" else "transcription_failed"),
        actor="system", details={"provider": tr.provider, "status": tr.status, "error": tr.error},
    )
    _checkpoint()

    transcription_ok = tr.status in {"completed", "skipped"}

    # --- Extraction ---
    source_text = corrected or transcript or (session.note_text if session else "") or ""
    # Authorized workspace vocabulary for model grounding: names this tenant
    # has actually used. The model may only match against these or text that
    # is literally present in the note — never invent geography.
    vocabulary_rows = (
        db.query(FieldObservation.field_name, FieldObservation.block_name, FieldObservation.crop)
        .filter(FieldObservation.tenant_id == observation.tenant_id)
        .filter(FieldObservation.status != "deleted")
        .order_by(FieldObservation.created_at.desc())
        .limit(200)
        .all()
    )
    workspace_fields = sorted({row[0] for row in vocabulary_rows if row[0]})
    workspace_blocks = sorted({row[1] for row in vocabulary_rows if row[1]})
    workspace_crops = sorted({row[2] for row in vocabulary_rows if row[2]})
    # Model-routed extraction is a paid capability; deterministic extraction
    # runs for everyone. The fallback label is truthful either way.
    from app.models.saas import Organization as _Organization
    from app.services.commercial_control import resolve_effective_entitlements as _resolve_ents

    _org = db.get(_Organization, observation.tenant_id)
    _allow_model = bool(_org) and _resolve_ents(db, _org).enabled("field_intelligence.model_extraction")
    extraction = extract_observation(
        source_text,
        field_hint=observation.field_name,
        block_hint=observation.block_name,
        crop_hint=observation.crop,
        event_type_hint=observation.event_type,
        occurred_at=observation.occurred_at,
        workspace_fields=workspace_fields,
        workspace_blocks=workspace_blocks,
        workspace_crops=workspace_crops,
        allow_model=_allow_model,
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
        model=extraction.method, attempt_count=int(job.attempt_count or 1),
        output={"confidence": extraction.confidence, "uncertain": extraction.uncertain_fields},
    )
    _audit(observation, "extraction_completed", actor="system", details={"confidence": extraction.confidence})
    _checkpoint()

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
    _link_evidence_record(db, observation, source_text=source_text, transcription_ok=transcription_ok)

    observation.status = "needs_review" if extraction.confidence < NEEDS_REVIEW_CONFIDENCE else "completed"
    observation.processing_error = None
    if session:
        session.status = "completed"
        session.completed_at = datetime.utcnow()
    db.flush()


def reprocess_observation(db: Session, ctx: AuthContext, observation_id: str) -> FieldObservation:
    """Re-enqueue processing for a failed/needs-review observation (no duplicates)."""
    observation = get_observation(db, ctx, observation_id)
    authorize_workspace_action(db, ctx, observation.workspace_id, write=True)
    require_capability(db, ctx, "field_intelligence.extraction")
    _enqueue_reprocess(db, observation, ctx_user_id=ctx.user.id)
    db.commit()
    db.refresh(observation)
    return observation


def _evidence_quality(observation: FieldObservation, confirmed_text: str) -> str:
    """Derive quality explicitly; real confidence (incl. 0.0) is never coerced."""
    if not (confirmed_text or "").strip():
        # No usable content: failed/blank transcription. Mark unusable so Ask /
        # Reports evidence consumers (which require usable) cannot read it.
        return "unusable"
    confidence = observation.confidence if observation.confidence is not None else 0.0
    return "needs_review" if confidence < NEEDS_REVIEW_CONFIDENCE else "usable"


def _apply_evidence_fields(
    record: EvidenceRecord,
    observation: FieldObservation,
    *,
    source_text: str,
    transcription_ok: bool | None = None,
) -> None:
    """Mirror the observation onto its evidence record — every consumer-visible
    field, so a correction never leaves stale text, provenance or quality behind."""
    confirmed_text = (source_text or "").strip()
    confidence = observation.confidence if observation.confidence is not None else 0.0
    record.title = (observation.field_name or "Field observation") + f" — {observation.event_type or 'observation'}"
    record.summary = (observation.summary or confirmed_text or "Field observation (no confirmed text)")[:2000]
    record.value_json = observation.structured_json or {}
    record.confidence = confidence
    record.quality_status = _evidence_quality(observation, confirmed_text)
    record.field_id = observation.field_id
    record.block_id = observation.block_id
    record.occurred_at = observation.occurred_at
    record.source_updated_at = datetime.utcnow()
    record.source_excerpt = (observation.corrected_transcript or observation.transcript or "")[:1000] or None
    metadata = dict(record.metadata_json or {})
    metadata.update(
        {
            "observation_id": observation.id,
            "capture_session_id": observation.capture_session_id,
            "source_mode": "field_capture",
            "provenance": observation.provenance_json,
            "quality_status": record.quality_status,
        }
    )
    if transcription_ok is not None:
        metadata["transcription_ok"] = transcription_ok
    record.metadata_json = metadata


def _link_evidence_record(db: Session, observation: FieldObservation, *, source_text: str, transcription_ok: bool) -> None:
    from app.services.field_intelligence_metrics import evidence_created

    evidence_created.inc()
    """Create/refresh an EvidenceRecord so the observation joins the graph.

    An untranscribed/failed voice capture with no confirmed text must NOT enter
    AGRO-AI as usable, confident evidence. Quality is derived explicitly and the
    real confidence (including 0.0) is preserved — never coerced to 0.5.
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
    if existing:
        _apply_evidence_fields(existing, observation, source_text=source_text, transcription_ok=transcription_ok)
        return
    record = EvidenceRecord(
        id=str(uuid.uuid4()),
        tenant_id=observation.tenant_id,
        workspace_id=observation.workspace_id,
        evidence_type="field_observation",
        units=None,
        citation_label=f"Field observation {observation.id[:8]}",
        metadata_json={},
    )
    _apply_evidence_fields(record, observation, source_text=source_text, transcription_ok=transcription_ok)
    db.add(record)
    db.flush()
    evidence_ids = list(observation.evidence_ids_json or [])
    evidence_ids.append(record.id)
    observation.evidence_ids_json = evidence_ids
    _audit(observation, "evidence_linked", actor="system", details={"evidence_id": record.id, "quality_status": record.quality_status})


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
    client_reported_duration: float | None = None,
) -> FieldObservationAsset:
    """Durably store an asset in R2/S3 and register its authorized reference.

    Never claims durability until the object store verifies the upload. Safe
    replay and same-content dedupe reuse the existing durable object.
    """
    organization_id = require_org(ctx)
    session = _load_session(db, organization_id, capture_ref)
    authorize_workspace_action(db, ctx, session.workspace_id, write=True)
    require_capability(db, ctx, "field_intelligence.capture")
    if kind in {"audio", "video"}:
        require_capability(db, ctx, "field_intelligence.voice")

    # Idempotent replay is resolved BEFORE any quota accounting: replaying an
    # already-stored asset consumes no new storage, so a tenant exactly at
    # quota can still safely retry an interrupted sync.
    existing = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.client_asset_id == client_asset_id)
        .first()
    )
    if existing and existing.status != "deleted":
        # Strict idempotency: identical intent replays; different intent conflicts.
        if _asset_matches(existing, content_sha256, size_bytes, kind, content_type):
            return existing  # safe replay: no re-upload, spool cleaned by caller
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "asset_idempotency_conflict",
                "message": "This client_asset_id already stored different content.",
                "asset_id": existing.id,
            },
        )

    # Same-content dedupe within the capture reuses the durable object. The
    # shared physical object is already accounted for, so no new quota is
    # reserved or consumed.
    twin = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.capture_session_id == session.id)
        .filter(FieldObservationAsset.content_sha256 == content_sha256)
        .filter(FieldObservationAsset.status == "stored")
        .first()
    )
    uploaded_new_ref: str | None = None
    reservation: FieldStorageReservation | None = None
    if twin:
        object_ref = twin.object_ref
        backend = twin.storage_backend
    else:
        # Reserve quota atomically BEFORE creating the physical object so
        # concurrent uploads can never overshoot the plan limit.
        reservation = reserve_storage(db, ctx, size_bytes, capture_session_id=session.id)
        store = _object_store()
        try:
            stored = store.put_path(
                spool_path,
                tenant_id=organization_id,
                connection_id=session.id,  # capture session is the storage scope
                filename=filename or f"{client_asset_id}",
                content_type=content_type,
                expected_sha256=content_sha256,
                expected_size=size_bytes,
                pending_registration=True,
            )
        except Exception:
            release_storage_reservation(db, reservation)
            raise
        object_ref = stored.uri
        backend = "s3"
        uploaded_new_ref = stored.uri  # track for compensating delete on race loss

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
        # server-measured duration only; the client's claim is metadata
        duration_seconds=duration_seconds,
        status="stored",
        metadata_json=(
            {"client_reported_duration_seconds": client_reported_duration}
            if client_reported_duration is not None
            else {}
        ),
    )
    db.add(asset)
    if reservation is not None:
        # The reservation converts into the registered row in the SAME
        # transaction: usage accounting never double-counts and never gaps.
        (
            db.query(FieldStorageReservation)
            .filter(FieldStorageReservation.id == reservation.id)
            .delete(synchronize_session=False)
        )
    manifest = list(session.asset_manifest_json or [])
    if not any(isinstance(m, dict) and m.get("client_asset_id") == client_asset_id for m in manifest):
        manifest.append({"client_asset_id": client_asset_id, "kind": kind, "content_type": content_type})
        session.asset_manifest_json = manifest
    try:
        db.commit()
    except IntegrityError:
        # Lost a concurrent race. If our upload created a *new* object that the
        # winning row does not reference, delete it so no orphan remains in R2.
        db.rollback()
        winner = (
            db.query(FieldObservationAsset)
            .filter(FieldObservationAsset.tenant_id == organization_id)
            .filter(FieldObservationAsset.capture_session_id == session.id)
            .filter(FieldObservationAsset.client_asset_id == client_asset_id)
            .first()
        )
        if uploaded_new_ref and (not winner or winner.object_ref != uploaded_new_ref):
            _compensate_object_upload(db, organization_id, session.id, uploaded_new_ref)
        release_storage_reservation(db, reservation)
        if winner:
            return winner
        raise
    except Exception:
        # ANY database failure after a successful R2 upload (connection loss,
        # constraint, disk, ...) must not leave an orphan durable object.
        db.rollback()
        if uploaded_new_ref:
            _compensate_object_upload(db, organization_id, session.id, uploaded_new_ref)
        release_storage_reservation(db, reservation)
        raise
    if uploaded_new_ref:
        # Promotion is best-effort: with the row durably committed, a leftover
        # marker is harmless — the reconciler sees the live reference and only
        # clears the marker.
        try:
            _object_store().promote(uploaded_new_ref, tenant_id=organization_id, connection_id=session.id)
        except Exception:  # noqa: BLE001
            logger.warning("field-intelligence pending-marker promotion failed (ref=%s)", uploaded_new_ref)
    db.refresh(asset)
    return asset


def _asset_matches(asset: FieldObservationAsset, sha256: str, size: int, kind: str, content_type: str | None) -> bool:
    return (
        (asset.content_sha256 or "") == sha256
        and int(asset.size_bytes or -1) == int(size)
        and (asset.kind or "") == kind
        and (asset.content_type or "") == (content_type or "")
    )


def _compensate_object_upload(db: Session, tenant_id: str, capture_session_id: str, object_ref: str) -> None:
    """Remove an uploaded object whose DB registration failed.

    A failed compensating delete is never silently swallowed: it durably stages
    an idempotent orphan-object-cleanup job so the object is removed later.
    """
    try:
        if not object_storage_configured():
            raise RuntimeError("object storage unavailable for compensating delete")
        store = get_object_store()
        store.delete(object_ref, tenant_id=tenant_id, connection_id=capture_session_id)
        try:
            store.promote(object_ref, tenant_id=tenant_id, connection_id=capture_session_id)
        except Exception:  # noqa: BLE001 - stale marker is reconciled later
            pass
        return
    except Exception:  # noqa: BLE001 - fall through to durable cleanup
        logger.exception(
            "field-intelligence compensating delete failed; staging orphan cleanup (tenant=%s ref=%s)",
            tenant_id, object_ref,
        )
    _stage_orphan_cleanup_job(db, tenant_id, capture_session_id, object_ref)


def _stage_orphan_cleanup_job(db: Session, tenant_id: str, capture_session_id: str, object_ref: str) -> None:
    """Durably stage an idempotent cleanup job for a possibly-orphaned object."""
    idempotency_key = f"fi-orphan-{hashlib.sha256(object_ref.encode('utf-8')).hexdigest()[:32]}"
    try:
        exists = (
            db.query(IngestionJob)
            .filter(IngestionJob.tenant_id == tenant_id)
            .filter(IngestionJob.idempotency_key == idempotency_key)
            .first()
        )
        if exists:
            return
        db.add(
            IngestionJob(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                job_type=ORPHAN_CLEANUP_JOB_TYPE,
                status="queued",
                input_json={"object_ref": object_ref, "capture_session_id": capture_session_id},
                output_json={},
                idempotency_key=idempotency_key,
                attempt_count=0,
                max_attempts=MAX_PROCESS_ATTEMPTS,
                next_attempt_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - the database itself is down
        db.rollback()
        logger.critical(
            "field-intelligence orphan cleanup could not be staged; object may be orphaned (tenant=%s ref=%s)",
            tenant_id, object_ref,
        )


def run_field_intelligence_orphan_cleanup(db: Session, *, limit: int = 25, worker_id: str | None = None) -> dict:
    """Durable worker: remove objects whose registration never became durable.

    Idempotent: a missing object deletes as a no-op; an object that gained a
    live DB reference in the meantime is left alone and the job completes.
    """
    worker_id = worker_id or f"orphan-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    candidates = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == ORPHAN_CLEANUP_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )
    cleaned = 0
    for job in candidates:
        if not _claim_job(db, job, worker_id):
            continue
        db.refresh(job)
        job_input = job.input_json or {}
        object_ref = job_input.get("object_ref")
        try:
            referenced = (
                db.query(FieldObservationAsset)
                .filter(FieldObservationAsset.tenant_id == job.tenant_id)
                .filter(FieldObservationAsset.object_ref == object_ref)
                .filter(FieldObservationAsset.status.in_(["stored", "pending_deletion"]))
                .count()
                if object_ref
                else 0
            )
            if object_ref and referenced == 0:
                if not object_storage_configured():
                    raise RuntimeError("object storage unavailable for orphan cleanup")
                store = get_object_store()
                store.delete(
                    object_ref, tenant_id=job.tenant_id, connection_id=job_input.get("capture_session_id")
                )
                try:
                    store.promote(
                        object_ref, tenant_id=job.tenant_id, connection_id=job_input.get("capture_session_id")
                    )
                except Exception:  # noqa: BLE001 - stale marker is reconciled later
                    pass
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.lease_expires_at = None
            job.worker_id = None
            job.output_json = {"referenced": referenced, "deleted": bool(object_ref and referenced == 0)}
            db.commit()
            cleaned += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            _fail_or_retry(db, job.id, exc)
    return {"cleaned": cleaned, "worker_id": worker_id}


def reconcile_pending_objects(db: Session, *, grace_seconds: int | None = None, limit: int = 500) -> dict:
    """Object-store-resident orphan recovery.

    Every new upload stages a pending-registration marker in the object store
    itself *before* the object bytes, so even total database unavailability —
    where neither the compensating delete nor the durable cleanup job could be
    recorded — leaves a store-resident trail. This reconciler:

    * skips markers younger than the grace period (upload may be in flight);
    * clears the marker (only) when the database shows a live reference —
      registration succeeded but promotion was lost;
    * deletes object + marker when no live reference exists after the grace
      period — the orphan case;
    * never deletes anything when the database cannot be consulted, and every
      step is idempotent, so retries are safe.
    """
    if not object_storage_configured():
        return {"status": "skipped", "reason": "object_storage_unconfigured"}
    grace = int(
        grace_seconds
        if grace_seconds is not None
        else getattr(settings, "FIELD_PENDING_OBJECT_GRACE_SECONDS", 21600)
    )
    cutoff = datetime.utcnow() - timedelta(seconds=grace)
    store = get_object_store()
    promoted = 0
    removed = 0
    skipped = 0
    errors = 0
    for entry in store.list_pending_registrations(limit=limit):
        uploaded_at = entry.get("uploaded_at")
        object_key = entry.get("key")
        object_uri = entry.get("uri")
        if uploaded_at is not None and uploaded_at > cutoff:
            skipped += 1
            continue  # inside the grace window; the upload may still be registering
        try:
            if object_uri:
                # The liveness check MUST succeed before any delete: if the
                # database is unavailable here, fail safe and keep the object.
                referenced = (
                    db.query(FieldObservationAsset)
                    .filter(FieldObservationAsset.object_ref == object_uri)
                    .filter(FieldObservationAsset.status.in_(["stored", "pending_deletion"]))
                    .count()
                )
                if referenced:
                    store.clear_pending_marker(entry["marker_key"])
                    promoted += 1
                    continue
                store.delete_unregistered_object(object_key)
            store.clear_pending_marker(entry["marker_key"])
            removed += 1
        except Exception:  # noqa: BLE001 - keep the object; retry next cycle
            db.rollback()
            errors += 1
            logger.exception("field-intelligence pending-object reconciliation failed (key=%s)", object_key)
    from app.services.field_intelligence_metrics import orphans_reconciled

    for outcome, count in (("promoted", promoted), ("removed", removed), ("skipped", skipped), ("errors", errors)):
        if count:
            orphans_reconciled.labels(outcome=outcome).inc(count)
    return {"status": "ok", "promoted": promoted, "removed": removed, "skipped": skipped, "errors": errors}


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
    authorize_workspace_action(db, ctx, asset.workspace_id)
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


def _range_not_satisfiable(total: int) -> HTTPException:
    # RFC 9110: a 416 carries Content-Range: bytes */<complete-length>.
    return HTTPException(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        detail="Requested range not satisfiable",
        headers={"Content-Range": f"bytes */{total}"},
    )


def resolve_byte_range(range_spec: tuple[int | None, int | None] | None, total: int) -> tuple[int, int, int] | None:
    """Resolve a parsed Range spec against the object size.

    ``(start, end)`` — bounded range; ``(start, None)`` — open-ended;
    ``(None, n)`` — suffix range (last ``n`` bytes). Raises 416 with
    ``Content-Range: bytes */total`` when unsatisfiable.
    """
    if range_spec is None:
        return None
    start, end = range_spec
    if start is None:
        # suffix range: bytes=-N
        if not end or total <= 0:
            raise _range_not_satisfiable(total)
        start = max(total - int(end), 0)
        end = total - 1
    else:
        if total <= 0 or start >= total:
            raise _range_not_satisfiable(total)
        end = total - 1 if end is None else min(int(end), total - 1)
        if start > end:
            raise _range_not_satisfiable(total)
    return int(start), int(end), total


def open_asset_stream(
    db: Session,
    ctx: AuthContext,
    asset_id: str,
    *,
    range_spec: tuple[int | None, int | None] | None = None,
):
    """Authorize an asset and return (asset, iterator, total_size, served_range).

    Streams from R2 without buffering the whole object in API memory. Retrieval
    is disabled the instant the asset leaves ``stored`` (deletion) or its
    observation is deleted. Supports bounded, open-ended and suffix ranges;
    unsatisfiable ranges raise 416 with ``Content-Range: bytes */total``.
    """
    organization_id = require_org(ctx)
    asset = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == organization_id)
        .filter(FieldObservationAsset.id == asset_id)
        .first()
    )
    if not asset or asset.status != "stored":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    authorize_workspace_action(db, ctx, asset.workspace_id)
    if asset.observation_id:
        observation = db.get(FieldObservation, asset.observation_id)
        if observation and observation.status == "deleted":
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Asset no longer available")
    store = _object_store()
    total = int(asset.size_bytes or 0)
    served_range = resolve_byte_range(range_spec, total)
    iterator = store.stream_object(
        asset.object_ref, tenant_id=organization_id, connection_id=asset.capture_session_id,
        byte_range=(served_range[0], served_range[1]) if served_range else None,
        chunk_size=int(settings.FIELD_ASSET_STREAM_CHUNK),
    )
    return asset, iterator, total, served_range


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
    authorize_workspace_action(db, ctx, asset.workspace_id, destructive=True)
    require_capability(db, ctx, "field_intelligence.retention")
    _mark_pending_deletion(db, asset)
    if asset.observation_id:
        observation = db.get(FieldObservation, asset.observation_id)
        if observation:
            _audit(observation, "asset_deleted", actor=ctx.user.id, details={"asset_id": asset_id})
    db.commit()  # first transaction commits pending_deletion + the deletion job


def _mark_pending_deletion(db: Session, asset: FieldObservationAsset) -> None:
    """First transaction: mark pending and stage an idempotent deletion job.

    The physical R2 delete happens later in the worker, in its own transaction.
    Retrieval is already disabled the moment status leaves ``stored``.
    """
    if asset.status in {"pending_deletion", "deleted"}:
        return
    asset.status = "pending_deletion"
    asset.deleted_at = datetime.utcnow()
    idempotency_key = f"fi-del-{asset.id}"
    exists = (
        db.query(IngestionJob)
        .filter(IngestionJob.tenant_id == asset.tenant_id)
        .filter(IngestionJob.idempotency_key == idempotency_key)
        .first()
    )
    if not exists:
        db.add(
            IngestionJob(
                id=str(uuid.uuid4()),
                tenant_id=asset.tenant_id,
                workspace_id=asset.workspace_id,
                job_type=ASSET_DELETE_JOB_TYPE,
                status="queued",
                input_json={"asset_id": asset.id},
                output_json={},
                idempotency_key=idempotency_key,
                attempt_count=0,
                max_attempts=MAX_PROCESS_ATTEMPTS,
                next_attempt_at=datetime.utcnow(),
            )
        )


# Process-local per-object locks (SQLite / single-node). On PostgreSQL the
# transaction-scoped advisory lock is authoritative across workers.
_OBJECT_DELETE_LOCKS: dict[str, threading.Lock] = {}
_OBJECT_DELETE_LOCKS_GUARD = threading.Lock()


def _advisory_lock_key(object_ref: str) -> int:
    return int.from_bytes(hashlib.sha256(object_ref.encode("utf-8")).digest()[:8], "big", signed=True)


@contextmanager
def _object_deletion_lock(db: Session, object_ref: str):
    """Serialize deletion decisions for one physical object.

    The lock must span the liveness count, the row transition AND the commit —
    otherwise two workers deleting two assets that share an ``object_ref`` can
    each observe the other as still live and neither performs the physical
    delete (or both do). On PostgreSQL a transaction advisory lock provides the
    cross-worker guarantee; elsewhere a process lock covers threaded workers on
    the single-writer database.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_lock_key(object_ref)})
        yield  # released when the surrounding transaction commits or rolls back
        return
    with _OBJECT_DELETE_LOCKS_GUARD:
        lock = _OBJECT_DELETE_LOCKS.setdefault(object_ref, threading.Lock())
    with lock:
        yield


def _execute_object_deletion(db: Session, asset: FieldObservationAsset) -> bool:
    """Worker step: physically remove the R2 object, confirm, mark deleted.

    Never marks ``deleted`` unless the object is confirmed gone (or there is no
    durable object / it is still shared). On failure the asset stays
    ``pending_deletion`` for retry. Callers must hold the object deletion lock
    and commit while it is held.
    """
    if asset.status == "deleted":
        return True
    if not asset.object_ref or asset.storage_backend != "s3":
        asset.status = "deleted"
        asset.object_deleted_at = datetime.utcnow()
        return True
    shared = (
        db.query(FieldObservationAsset)
        .filter(FieldObservationAsset.tenant_id == asset.tenant_id)
        .filter(FieldObservationAsset.object_ref == asset.object_ref)
        .filter(FieldObservationAsset.id != asset.id)
        .filter(FieldObservationAsset.status.in_(["stored", "pending_deletion"]))
        .count()
    )
    try:
        if shared == 0:
            if not object_storage_configured():
                asset.delete_attempts = int(asset.delete_attempts or 0) + 1
                return False  # storage unavailable -> remain pending_deletion
            get_object_store().delete(
                asset.object_ref, tenant_id=asset.tenant_id, connection_id=asset.capture_session_id
            )
            from app.services.field_intelligence_metrics import objects_deleted

            objects_deleted.inc()
        asset.status = "deleted"
        asset.object_deleted_at = datetime.utcnow()
        return True
    except Exception:  # noqa: BLE001 - remain pending for retry, never lose the row
        asset.delete_attempts = int(asset.delete_attempts or 0) + 1
        return False


def run_field_intelligence_deletions(db: Session, *, limit: int = 50, worker_id: str | None = None) -> dict:
    """Durable worker: process staged asset-deletion jobs (leased, retried)."""
    worker_id = worker_id or f"del-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()
    candidates = (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == ASSET_DELETE_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .filter((IngestionJob.lease_expires_at.is_(None)) | (IngestionJob.lease_expires_at <= now))
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )
    deleted = 0
    for job in candidates:
        if not _claim_job(db, job, worker_id):
            continue
        db.refresh(job)
        asset = db.get(FieldObservationAsset, (job.input_json or {}).get("asset_id"))
        if not asset:
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.lease_expires_at = None
            db.commit()
            continue
        try:
            # The lock spans count -> transition -> COMMIT so that concurrent
            # deletion of assets sharing one object_ref resolves to exactly one
            # physical object deletion.
            with _object_deletion_lock(db, asset.object_ref or asset.id):
                ok = _execute_object_deletion(db, asset)
                if ok:
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    job.lease_expires_at = None
                    job.worker_id = None
                    db.commit()
                    deleted += 1
                else:
                    db.commit()
            if not ok:
                _fail_or_retry(db, job.id, RuntimeError("object_deletion_incomplete"))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            _fail_or_retry(db, job.id, exc)
    return {"deleted": deleted, "worker_id": worker_id}


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
    # Direct-ID access is workspace-authorized, never tenant-filtered only.
    authorize_workspace_action(db, ctx, observation.workspace_id)
    return observation


# Statuses a user may set through the generic PATCH endpoint. Destructive and
# internal-processing states are intentionally excluded — DELETE is the only
# destructive path, and processing state is owned by the worker.
USER_SETTABLE_STATUSES = {"needs_review", "acknowledged", "completed"}


def patch_observation(db: Session, ctx: AuthContext, observation_id: str, changes: dict) -> FieldObservation:
    observation = get_observation(db, ctx, observation_id)
    authorize_workspace_action(db, ctx, observation.workspace_id, write=True)
    corrected = changes.get("corrected_transcript")
    correction_changed = corrected is not None and corrected != (observation.corrected_transcript or "")
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
        if changes["status"] not in USER_SETTABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_status", "message": "That status cannot be set via patch.", "allowed": sorted(USER_SETTABLE_STATUSES)},
            )
        observation.status = changes["status"]
    _audit(observation, "observation_corrected", actor=ctx.user.id, details={"fields": sorted(changes.keys())})
    # A transcript correction re-runs extraction/correlation/evidence downstream.
    if correction_changed:
        _enqueue_reprocess(db, observation, ctx_user_id=ctx.user.id)
    else:
        _refresh_linked_evidence(db, observation)
    db.commit()
    db.refresh(observation)
    return observation


def _has_active_process_job(db: Session, observation_id: str) -> bool:
    return (
        db.query(IngestionJob)
        .filter(IngestionJob.job_type == PROCESS_JOB_TYPE)
        .filter(IngestionJob.status.in_(["queued", "running"]))
        .filter(IngestionJob.input_json["observation_id"].as_string() == observation_id)
        .first()
        is not None
        if db.bind and db.bind.dialect.name == "postgresql"
        else any(
            (j.input_json or {}).get("observation_id") == observation_id
            for j in db.query(IngestionJob)
            .filter(IngestionJob.job_type == PROCESS_JOB_TYPE)
            .filter(IngestionJob.status.in_(["queued", "running"]))
            .all()
        )
    )


def _enqueue_reprocess(db: Session, observation: FieldObservation, *, ctx_user_id: str | None) -> bool:
    """Stage a reprocess job unless one is already active (no duplicates)."""
    if _has_active_process_job(db, observation.id):
        return False
    observation.status = "staged"
    observation.processing_error = None
    _audit(observation, "reprocess_requested", actor=ctx_user_id or "system")
    db.add(
        IngestionJob(
            id=str(uuid.uuid4()),
            tenant_id=observation.tenant_id,
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
    )
    return True


def _refresh_linked_evidence(db: Session, observation: FieldObservation) -> None:
    """Fully re-mirror the evidence record after a non-transcript patch
    (field/block/severity/structured/status edits that skip reprocessing)."""
    record = _find_evidence_slow(db, observation)
    if record:
        session = db.get(FieldCaptureSession, observation.capture_session_id) if observation.capture_session_id else None
        source_text = (
            observation.corrected_transcript
            or observation.transcript
            or (session.note_text if session else None)
            or ""
        )
        _apply_evidence_fields(record, observation, source_text=source_text)


def delete_observation(db: Session, ctx: AuthContext, observation_id: str) -> None:
    observation = get_observation(db, ctx, observation_id)
    authorize_workspace_action(db, ctx, observation.workspace_id, destructive=True)
    require_capability(db, ctx, "field_intelligence.retention")
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
        _mark_pending_deletion(db, asset)
    # remove linked evidence from the graph
    evidence = _find_evidence_slow(db, observation)
    if evidence:
        db.delete(evidence)
    db.commit()


def create_task_from_observation(db: Session, ctx: AuthContext, observation_id: str, payload: dict) -> dict:
    from app.services.field_intelligence_metrics import tasks_created

    tasks_created.inc()
    from app.services.field_operating_loop import build_field_ops_context, create_task

    observation = get_observation(db, ctx, observation_id)
    authorize_workspace_action(db, ctx, observation.workspace_id, write=True)
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
    require_capability(db, ctx, "field_intelligence.map")
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

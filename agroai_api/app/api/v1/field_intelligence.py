"""Field Intelligence API — durable voice-first / offline field capture.

Tenant and workspace context is always resolved through the authenticated
dependency; a tenant id in the request body is never trusted. Processing is
staged onto a durable job (HTTP 202) and never blocks the request on external
transcription.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import date, datetime, timezone
from datetime import date as date_type
from decimal import Decimal
from typing import Literal

import json
import re

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.services import crop_estimation
from app.services import field_intelligence as svc
from app.services.crop_intelligence import field_condition_summary
from app.services.crop_profiles import all_profiles, resolve_profile
from app.services.field_live_rate_limit import check_field_live_analysis_limit
from app.services.field_transcription import transcribe_audio
from app.services.field_vision import analyze_field_images
from app.services.media_inspection import (
    inspect_media_file,
    validate_media_for_kind,
    verify_capped_media_duration,
)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\]")


def _sanitize_filename(name: str | None) -> str:
    cleaned = _CONTROL_CHARS.sub("_", (name or "asset").strip()) or "asset"
    return cleaned[:200]

def enforce_field_intelligence_release(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> None:
    """Server-side release gate for every Field Intelligence route.

    The kill switch and release state are authoritative here — frontend locks
    are UX only. Runs after the canonical account/organization enforcement in
    ``get_auth_context`` so restricted accounts keep their existing 403s.
    """
    from app.services.field_intelligence_metrics import rollout_requests
    from app.services.field_intelligence_rollout import field_intelligence_access

    allowed, state, cohort = field_intelligence_access(db, ctx.organization)
    rollout_requests.labels(state=state, cohort=cohort, allowed=str(allowed).lower()).inc()
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "field_intelligence_not_released",
                "release_state": state,
                "message": "Field Intelligence is not enabled for this organization yet.",
            },
        )


router = APIRouter(
    prefix="/field-intelligence",
    tags=["field-intelligence"],
    dependencies=[Depends(enforce_field_intelligence_release)],
)


def enforce_json_body_limit(request: Request) -> None:
    """Reject oversized JSON bodies from the declared Content-Length before
    model parsing runs (chunked bodies without a length still hit the
    post-parse byte checks)."""
    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > int(settings.FIELD_SYNC_MAX_BODY_BYTES):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Request body too large",
        )

_KIND_MAGIC: dict[str, list[bytes]] = {
    "audio": [b"OggS", b"ID3", b"RIFF", b"\x1aE\xdf\xa3", b"fLaC", b"ftyp", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
    "video": [b"\x1aE\xdf\xa3", b"ftyp", b"RIFF", b"OggS"],
    "photo": [b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM"],
}
_MAX_TEXT = 8000
_MAX_NAME = 200


def drain_field_intelligence_processing() -> None:
    """Opportunistically advance staged processing jobs on their own session.

    The job is already durably staged; this is a best-effort in-process nudge so
    dev/single-node deployments progress without a separate worker. A crashed
    process simply leaves the durable job for the next drain/worker.
    """
    db = SessionLocal()
    try:
        svc.run_field_intelligence_jobs(db, limit=10)
    except Exception:  # noqa: BLE001 - background best-effort
        db.rollback()
    finally:
        db.close()


def _bounded_metadata(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    serialized = json.dumps(value, default=str)
    if len(serialized) > 8000:
        raise ValueError("metadata too large")
    if _json_depth(value) > 5:
        raise ValueError("metadata nested too deeply")
    return value


def _json_depth(value, depth: int = 1) -> int:
    if isinstance(value, dict):
        return max([depth] + [_json_depth(v, depth + 1) for v in value.values()])
    if isinstance(value, list):
        return max([depth] + [_json_depth(v, depth + 1) for v in value])
    return depth


class AssetManifestItem(BaseModel):
    """Strict manifest entry: bounded fields, unknown keys rejected.

    The persisted manifest and the idempotency-fingerprinted manifest are both
    derived from exactly these three fields, so they can never diverge.
    """

    model_config = ConfigDict(extra="forbid")

    client_asset_id: str = Field(min_length=1, max_length=_MAX_NAME)
    kind: Literal["audio", "video", "photo", "file"]
    content_type: str = Field(min_length=1, max_length=200)


class CaptureInitiateRequest(BaseModel):
    client_capture_id: str = Field(max_length=_MAX_NAME)
    idempotency_key: str | None = Field(default=None, max_length=120)
    workspace_id: str | None = Field(default=None, max_length=_MAX_NAME)
    capture_source: Literal["voice", "typed"] = "typed"
    note_text: str | None = Field(default=None, max_length=_MAX_TEXT)
    transcript_preview: str | None = Field(default=None, max_length=_MAX_TEXT)
    field_id: str | None = Field(default=None, max_length=_MAX_NAME)
    field_name: str | None = Field(default=None, max_length=_MAX_NAME)
    block_id: str | None = Field(default=None, max_length=_MAX_NAME)
    block_name: str | None = Field(default=None, max_length=_MAX_NAME)
    crop: str | None = Field(default=None, max_length=_MAX_NAME)
    event_type: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, max_length=32)
    assignee: str | None = Field(default=None, max_length=_MAX_NAME)
    occurred_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_accuracy_m: float | None = None
    asset_manifest: list[AssetManifestItem] = Field(default_factory=list, max_length=25)
    metadata: dict = Field(default_factory=dict)
    client_created_at: datetime | None = None

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v):
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("latitude out of range")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v):
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("longitude out of range")
        return v

    @field_validator("metadata")
    @classmethod
    def _meta(cls, v):
        return _bounded_metadata(v or {})


class SyncCaptureItem(CaptureInitiateRequest):
    """A batch item carries the same constraints as a single initiation, plus
    the optional completion fields."""
    corrected_transcript: str | None = Field(default=None, max_length=_MAX_TEXT)
    language: str | None = Field(default="en", max_length=16)


class CaptureCompleteRequest(BaseModel):
    corrected_transcript: str | None = Field(default=None, max_length=_MAX_TEXT)
    language: str | None = Field(default="en", max_length=16)


class SyncBatchRequest(BaseModel):
    captures: list[SyncCaptureItem] = Field(min_length=1)


_LIVE_FRAME_MAX_BYTES = 1_500_000
_LIVE_FRAME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_LIVE_AUDIO_MAX_BYTES = 4_000_000
_LIVE_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav",
    "audio/x-wav", "audio/flac", "video/webm", "video/mp4",
}
_LANGUAGE_HINT = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")


def _normalized_language(value: str | None) -> str | None:
    candidate = str(value or "").strip()[:16]
    return candidate if candidate and _LANGUAGE_HINT.fullmatch(candidate) else None


def _valid_live_frame(payload: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


@router.post("/live-analysis")
async def live_field_analysis(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: str | None = Form(default=None, max_length=_MAX_NAME),
    field_name: str | None = Form(default=None, max_length=_MAX_NAME),
    crop: str | None = Form(default=None, max_length=_MAX_NAME),
    note_text: str | None = Form(default=None, max_length=1600),
    language: str | None = Form(default=None, max_length=16),
    frame_timestamp_seconds: float | None = Form(default=None, ge=0, le=900),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    """Analyze one sampled video frame without persisting it.

    This is deliberately near-real-time rather than continuous video inference:
    the durable uploaded recording remains the authoritative evidence, while the
    sampled response is preliminary guidance that always requires review.
    """
    organization_id = svc.require_org(ctx)
    if workspace_id:
        svc.authorize_workspace_action(db, ctx, workspace_id)

    decision = check_field_live_analysis_limit(organization_id, ctx.user.id, channel="vision")
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "field_live_analysis_rate_limited",
                "message": "Live analysis is temporarily rate limited. The recording continues and will be fully analyzed after upload.",
            },
            headers={"Retry-After": str(decision.retry_after)},
        )

    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > _LIVE_FRAME_MAX_BYTES + 100_000:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")

    content_type = str(file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _LIVE_FRAME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported live frame type")
    payload = await file.read(_LIVE_FRAME_MAX_BYTES + 1)
    await file.close()
    if not payload or len(payload) > _LIVE_FRAME_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Live frame exceeds size limit")
    if not _valid_live_frame(payload, content_type):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Live frame content is invalid")

    context = {
        "field_name": field_name,
        "crop": crop,
        "note_text": note_text,
        "language": _normalized_language(language) or "en",
        "media_kind": "live_video_frame",
        "frame_timestamp_seconds": frame_timestamp_seconds,
    }
    result = await run_in_threadpool(analyze_field_images, [(payload, content_type, context)], context)
    if not result.succeeded:
        return {
            "status": "unavailable",
            "preliminary": True,
            "durable": False,
            "error": result.error or "live_vision_unavailable",
            "retryable": bool(result.retryable),
            "latency_ms": result.latency_ms,
            "rate_limit_remaining": decision.remaining,
        }
    return {
        "status": "ok",
        "preliminary": True,
        "durable": False,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "frame_timestamp_seconds": frame_timestamp_seconds,
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        # "degraded" means the provider answered in prose rather than the
        # structured contract: show it for review, never as a finding.
        "analysis_state": result.analysis.get("analysis_state", "structured"),
        "provider_fallback": bool(result.analysis.get("images_fallback_model")),
        "confidence_kind": result.analysis.get("confidence_kind"),
        "analysis": result.analysis,
        "human_review_required": True,
        "rate_limit_remaining": decision.remaining,
    }


@router.post("/live-transcription")
async def live_field_transcription(
    request: Request,
    file: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=16),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    # Transcribe one short, non-persisted audio segment during recording.
    # Browser speech recognition remains the lowest-latency caption source when
    # available. This endpoint provides a multilingual server fallback and
    # correction lane. The chunk is bounded, processed in memory, and discarded.
    # The durable uploaded recording remains the authoritative evidence.
    organization_id = svc.require_org(ctx)
    decision = check_field_live_analysis_limit(
        organization_id, ctx.user.id, channel="speech"
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "field_live_transcription_rate_limited",
                "message": "Live captions are temporarily rate limited. Recording continues and the full upload will still be transcribed.",
            },
            headers={"Retry-After": str(decision.retry_after)},
        )

    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > _LIVE_AUDIO_MAX_BYTES + 100_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Live speech segment exceeds size limit",
        )
    content_type = str(file.content_type or "").lower().split(";")[0].strip()
    if content_type not in _LIVE_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported live speech media type",
        )
    payload = await file.read(_LIVE_AUDIO_MAX_BYTES + 1)
    await file.close()
    if not payload or len(payload) > _LIVE_AUDIO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Live speech segment exceeds size limit",
        )

    result = await run_in_threadpool(
        transcribe_audio,
        audio=payload,
        content_type=content_type,
        language=_normalized_language(language),
        note_text=None,
    )
    if not result.succeeded:
        return {
            "status": "unavailable",
            "preliminary": True,
            "durable": False,
            "error": result.error or "live_transcription_unavailable",
            "retryable": bool(result.retryable),
            "language": result.language or _normalized_language(language),
            "rate_limit_remaining": decision.remaining,
        }
    return {
        "status": "ok",
        "preliminary": True,
        "durable": False,
        "transcript": result.transcript,
        "language": result.language or _normalized_language(language),
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "rate_limit_remaining": decision.remaining,
    }


PATCH_STATUSES = ("needs_review", "acknowledged", "completed")


class ObservationPatchRequest(BaseModel):
    corrected_transcript: str | None = Field(default=None, max_length=_MAX_TEXT)
    field_id: str | None = Field(default=None, max_length=_MAX_NAME)
    field_name: str | None = Field(default=None, max_length=_MAX_NAME)
    block_id: str | None = Field(default=None, max_length=_MAX_NAME)
    block_name: str | None = Field(default=None, max_length=_MAX_NAME)
    crop: str | None = Field(default=None, max_length=_MAX_NAME)
    event_type: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, max_length=32)
    # Only non-destructive, non-internal statuses may be set via PATCH.
    status: Literal["needs_review", "acknowledged", "completed"] | None = None
    structured: dict | None = None

    @field_validator("structured")
    @classmethod
    def _structured(cls, v):
        if v is None:
            return v
        if len(json.dumps(v, default=str)) > 8000:
            raise ValueError("structured patch too large")
        return v


class TaskCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=_MAX_NAME)
    assigned_to: str | None = Field(default=None, max_length=_MAX_NAME)
    priority: Literal["high", "medium", "low"] | None = None
    why: str | None = Field(default=None, max_length=_MAX_TEXT)
    instructions: list[str] = Field(default_factory=list, max_length=50)
    evidence_required: list[str] = Field(default_factory=list, max_length=50)


# ---------------------------------------------------------------------------
# Captures
# ---------------------------------------------------------------------------

@router.post("/captures/initiate", dependencies=[Depends(enforce_json_body_limit)])
def initiate_capture(
    payload: CaptureInitiateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    session = svc.initiate_capture(db, ctx, payload.model_dump())
    return {"status": "accepted", "capture": svc.serialize_capture(session)}


@router.post("/captures/{capture_id}/assets")
async def upload_asset(
    capture_id: str,
    client_asset_id: str = Form(..., max_length=_MAX_NAME),
    kind: Literal["audio", "video", "photo", "file"] = Form(...),
    duration_seconds: float | None = Form(default=None),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.field_intelligence_metrics import (
        asset_upload_bytes, asset_upload_latency, media_validation_failures,
    )
    import time as _time

    _upload_started = _time.monotonic()
    max_bytes = int(settings.FIELD_ASSET_MAX_BYTES)
    digest = hashlib.sha256()
    total = 0
    head = b""
    spool = tempfile.NamedTemporaryFile(prefix="agroai-field-", delete=False)
    spool_path = spool.name
    try:
        while True:
            chunk = await file.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Asset exceeds size limit")
            if len(head) < 16:
                head += chunk[: 16 - len(head)]
            digest.update(chunk)
            spool.write(chunk)
        spool.flush()
        spool.close()
        if total == 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty asset")

        # Real media inspection: parse actual container tracks and measure
        # duration server-side under a hard budget. The browser-supplied
        # duration is never trusted for limits or persisted as authoritative.
        measured_duration: float | None = None
        if kind == "file":
            if not _content_matches_kind(kind, head, file.content_type):
                raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Content does not match declared media type")
        else:
            inspection = inspect_media_file(spool_path)
            ok, reason = validate_media_for_kind(
                inspection, kind=kind, content_type=file.content_type,
                max_audio_seconds=float(settings.FIELD_AUDIO_MAX_SECONDS),
            )
            if not ok:
                if reason == "duration_exceeds_limit":
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                        detail={"code": "duration_exceeds_limit", "message": "Media exceeds the duration limit."})
                media_validation_failures.labels(reason=str(reason or "unknown")[:60]).inc()
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail={"code": "media_rejected", "reason": reason,
                            "message": "Content does not match the declared media type or is unsupported."},
                )
            measured_duration = inspection.duration_seconds
            if kind in {"audio", "video"}:
                # Duration caps bind on the *verified* packet timeline. Audio and
                # video whose real duration cannot be measured by the bounded
                # probe are rejected — the container header (and the browser)
                # only ever claim a duration; they never prove one.
                verified, probe_reason, verified_duration = verify_capped_media_duration(
                    spool_path, inspection, kind=kind,
                    max_seconds=float(settings.FIELD_AUDIO_MAX_SECONDS),
                    ffprobe_path=str(settings.FIELD_MEDIA_FFPROBE_PATH or "ffprobe"),
                    timeout_seconds=float(settings.FIELD_MEDIA_PROBE_TIMEOUT_SECONDS),
                    max_output_bytes=int(settings.FIELD_MEDIA_PROBE_MAX_OUTPUT_BYTES),
                    memory_limit_mb=int(settings.FIELD_MEDIA_PROBE_MEMORY_LIMIT_MB),
                )
                if not verified:
                    if probe_reason == "duration_exceeds_limit":
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail={"code": "duration_exceeds_limit",
                                    "message": "Media exceeds the duration limit."},
                        )
                    media_validation_failures.labels(reason=str(probe_reason or "unverifiable")[:60]).inc()
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={"code": "media_unverifiable", "reason": probe_reason,
                                "message": "Media duration or structure could not be verified."},
                    )
                measured_duration = verified_duration

        asset = svc.register_asset(
            db, ctx, capture_id,
            client_asset_id=client_asset_id, kind=kind, content_type=file.content_type,
            filename=_sanitize_filename(file.filename), content_sha256=digest.hexdigest(), size_bytes=total,
            duration_seconds=measured_duration, spool_path=spool_path,
            client_reported_duration=duration_seconds,
        )
        asset_upload_bytes.labels(kind=kind).observe(total)
        asset_upload_latency.labels(kind=kind).observe(_time.monotonic() - _upload_started)
        return {"status": "stored", "asset": svc._serialize_asset(asset)}
    finally:
        # Always reclaim the spool — durable copy lives in R2, dedupe/replay
        # and every error path must not leave an orphan temp file.
        _safe_unlink(spool_path)


@router.post("/captures/{capture_id}/complete", status_code=status.HTTP_202_ACCEPTED)
def complete_capture(
    capture_id: str,
    payload: CaptureCompleteRequest,
    background: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    observation = svc.complete_capture(db, ctx, capture_id, payload.model_dump())
    background.add_task(drain_field_intelligence_processing)
    return {
        "status": "accepted",
        "processing": observation.status not in {"completed", "needs_review", "failed"},
        "observation": svc.serialize_observation(db, observation, include_runs=True),
    }


@router.get("/captures/{capture_id}")
def get_capture(
    capture_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    organization_id = svc.require_org(ctx)
    session = svc._load_session(db, organization_id, capture_id)
    svc.authorize_workspace_action(db, ctx, session.workspace_id)
    return {"status": "ok", "capture": svc.serialize_capture(session)}


@router.post("/sync/batch", dependencies=[Depends(enforce_json_body_limit)])
def sync_batch(
    payload: SyncBatchRequest,
    background: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    if len(payload.captures) > int(settings.FIELD_SYNC_MAX_BATCH):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Sync batch too large")
    items = [item.model_dump() for item in payload.captures]
    if len(json.dumps(items, default=str)) > int(settings.FIELD_SYNC_MAX_BODY_BYTES):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Sync batch body too large")
    result = svc.sync_batch(db, ctx, items)
    background.add_task(drain_field_intelligence_processing)
    return {"status": "processed", **result}


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

@router.get("/observations")
def list_observations(
    workspace_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    field_id: str | None = Query(default=None),
    block_id: str | None = Query(default=None),
    crop: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    author: str | None = Query(default=None),
    obs_status: str | None = Query(default=None, alias="status"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    filters = {
        "workspace_id": workspace_id, "q": q, "field_id": field_id, "block_id": block_id,
        "crop": crop, "event_type": event_type, "severity": severity, "status": obs_status,
        "author": author, "start": start, "end": end, "limit": limit, "offset": offset,
    }
    rows, total = svc.list_observations(db, ctx, filters)
    return {
        "status": "ok",
        "observations": [svc.serialize_observation(db, obs) for obs in rows],
        "count": len(rows), "total": total, "limit": limit, "offset": offset,
    }


@router.get("/search")
def search(
    q: str = Query(...),
    workspace_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = svc.list_observations(db, ctx, {"q": q, "workspace_id": workspace_id, "limit": limit, "offset": offset})
    return {"status": "ok", "query": q, "observations": [svc.serialize_observation(db, obs) for obs in rows], "count": len(rows), "total": total}


@router.get("/map")
def map_view(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    data = svc.map_observations(db, ctx, {"workspace_id": workspace_id})
    data["map_style_configured"] = bool(settings.FIELD_MAP_STYLE_URL)
    data["map_style_url"] = settings.FIELD_MAP_STYLE_URL or None
    return {"status": "ok", **data}


@router.get("/observations/{observation_id}")
def get_observation(
    observation_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    observation = svc.get_observation(db, ctx, observation_id)
    return {"status": "ok", "observation": svc.serialize_observation(db, observation, include_runs=True)}


@router.patch("/observations/{observation_id}")
def patch_observation(
    observation_id: str,
    payload: ObservationPatchRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    changes = {key: value for key, value in payload.model_dump().items() if value is not None}
    observation = svc.patch_observation(db, ctx, observation_id, changes)
    return {"status": "updated", "observation": svc.serialize_observation(db, observation, include_runs=True)}


@router.delete("/observations/{observation_id}")
def delete_observation(
    observation_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    svc.delete_observation(db, ctx, observation_id)
    return {"status": "deleted", "observation_id": observation_id}


@router.post("/observations/{observation_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess_observation(
    observation_id: str,
    background: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    observation = svc.reprocess_observation(db, ctx, observation_id)
    background.add_task(drain_field_intelligence_processing)
    return {"status": "accepted", "observation": svc.serialize_observation(db, observation, include_runs=True)}


@router.post("/observations/{observation_id}/tasks")
def create_task(
    observation_id: str,
    payload: TaskCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    task = svc.create_task_from_observation(db, ctx, observation_id, payload.model_dump())
    return {"status": "created", "task": task}


# ---------------------------------------------------------------------------
# Crop Intelligence: detections, field condition, harvest window, production
# ---------------------------------------------------------------------------

_MAX_WEATHER_DAYS = 400
_MAX_ANALOG_YEARS = 30


class WeatherDayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date_type
    tmax_c: float
    tmin_c: float


class MaturityTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_gdd: float = Field(gt=0, le=20000)
    high_gdd: float = Field(gt=0, le=20000)
    source: str = Field(min_length=1, max_length=500)
    source_type: Literal["supplier_published", "grower_historical", "fitted_model"]
    variety: str | None = Field(default=None, max_length=_MAX_NAME)


class HarvestWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop: str | None = Field(default=None, max_length=_MAX_NAME)
    biofix: date
    biofix_type: Literal["planting", "transplant", "emergence", "bud_break", "bloom", "other"]
    as_of: date
    degree_day_method: Literal["simple_average", "modified_average_86_50"] | None = None
    base_c: float | None = Field(default=None, ge=-10, le=40)
    upper_cutoff_c: float | None = Field(default=None, ge=0, le=50)
    target: MaturityTargetIn | None = None
    observed: list[WeatherDayIn] = Field(default_factory=list, max_length=_MAX_WEATHER_DAYS)
    analog_years: dict[int, list[WeatherDayIn]] = Field(default_factory=dict)
    weather_source: str | None = Field(default=None, max_length=500)

    @field_validator("analog_years")
    @classmethod
    def _analog_years(cls, value):
        if len(value) > _MAX_ANALOG_YEARS:
            raise ValueError(f"at most {_MAX_ANALOG_YEARS} analog years")
        for year, days in value.items():
            if not (1900 <= int(year) <= 2200) or len(days) > 366:
                raise ValueError("analog years need a plausible year and at most 366 days each")
        return value


class EstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    standard_error: float = Field(ge=0)


class ProductionEstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = Field(min_length=1, max_length=40)
    object_label: str = Field(min_length=1, max_length=60)
    design: str = Field(min_length=1, max_length=60)
    population_units: int = Field(ge=1, le=100_000_000)
    sample_counts: list[float] = Field(min_length=1, max_length=5000)
    count_source: str = Field(min_length=1, max_length=60)
    detector_validation_id: str | None = Field(default=None, max_length=_MAX_NAME)
    detection_rate: EstimateIn | None = None
    unit_weight_kg: EstimateIn | None = None
    marketable_fraction: EstimateIn | None = None
    area_hectares: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000"))
    include_market_proposal: bool = False


def _estimate(value: EstimateIn | None) -> crop_estimation.Estimate | None:
    return None if value is None else crop_estimation.Estimate(value.value, value.standard_error)


def _weather(days: list[WeatherDayIn]) -> list[crop_estimation.WeatherDay]:
    return [crop_estimation.WeatherDay(item.date, item.tmax_c, item.tmin_c) for item in days]


@router.get("/crop-profiles")
def crop_profiles() -> dict:
    """Supported crop vocabularies and conventions; none is validated yet."""
    return {"status": "ok", "profiles": [profile.to_dict() for profile in all_profiles()]}


@router.get("/observations/{observation_id}/detections")
def observation_detections(
    observation_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    observation = svc.get_observation(db, ctx, observation_id)
    structured = observation.structured_json if isinstance(observation.structured_json, dict) else {}
    provenance = observation.provenance_json if isinstance(observation.provenance_json, dict) else {}
    detections = structured.get("detections") if isinstance(structured.get("detections"), dict) else None
    return {
        "status": "ok",
        "observation_id": observation.id,
        "detection_status": provenance.get("detection_status") or ("completed" if detections else "not_run"),
        "detection_reason": provenance.get("detection_reason"),
        "detections": detections,
        "human_review_required": True,
    }


@router.get("/fields/{field_id}/crop-condition")
def field_crop_condition(
    field_id: str,
    workspace_id: str | None = Query(default=None),
    block_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    rows, total = svc.list_observations(db, ctx, {
        "workspace_id": workspace_id, "field_id": field_id, "block_id": block_id, "limit": limit, "offset": 0,
    })
    summary = field_condition_summary([svc.serialize_observation(db, obs) for obs in rows], field_id=field_id)
    return {"status": "ok", "total_observations": total, **{k: v for k, v in summary.items() if k != "status"},
            "summary_status": summary["status"]}


@router.post("/crop-intelligence/harvest-window", dependencies=[Depends(enforce_json_body_limit)])
def harvest_window(payload: HarvestWindowIn) -> dict:
    """Harvest window from supplied, sourced inputs. Nothing is persisted."""
    profile = resolve_profile(payload.crop)
    method = payload.degree_day_method
    base = payload.base_c
    upper = payload.upper_cutoff_c
    if method is None and profile is not None and profile.degree_day_method is not None:
        method = profile.degree_day_method.method
        base = profile.degree_day_method.base_c if base is None else base
        upper = profile.degree_day_method.upper_cutoff_c if upper is None else upper
    if method is None or base is None:
        return {
            "status": "insufficient_evidence", "window": None, "crop_id": profile.crop_id if profile else None,
            "reasons": ["degree_day_method_and_base_temperature_required"],
        }
    target = None if payload.target is None else crop_estimation.MaturityTarget(
        low_gdd=payload.target.low_gdd, high_gdd=payload.target.high_gdd, source=payload.target.source,
        source_type=payload.target.source_type, variety=payload.target.variety,
    )
    result = crop_estimation.estimate_harvest_window(crop_estimation.HarvestWindowRequest(
        biofix=payload.biofix, biofix_type=payload.biofix_type, as_of=payload.as_of,
        config=crop_estimation.DegreeDayConfig(method, float(base), None if upper is None else float(upper)),
        target=target, observed=_weather(payload.observed),
        analog_years={int(year): _weather(days) for year, days in payload.analog_years.items()},
        crop_id=profile.crop_id if profile else None,
    ))
    result["weather_source"] = payload.weather_source
    return result


@router.post("/crop-intelligence/production-estimate", dependencies=[Depends(enforce_json_body_limit)])
def production_estimate(payload: ProductionEstimateIn) -> dict:
    """Production from a sampling design. Nothing is persisted or applied;
    an optional Market Intelligence proposal must be reviewed and submitted
    by a person with write access."""
    result = crop_estimation.estimate_production(crop_estimation.ProductionRequest(
        unit=payload.unit, object_label=payload.object_label, design=payload.design,
        population_units=payload.population_units, sample_counts=payload.sample_counts,
        count_source=payload.count_source, detection_rate=_estimate(payload.detection_rate),
        unit_weight_kg=_estimate(payload.unit_weight_kg), marketable_fraction=_estimate(payload.marketable_fraction),
        area_hectares=payload.area_hectares, detector_validation_id=payload.detector_validation_id,
    ))
    if payload.include_market_proposal:
        estimate_id = "crop-est-" + hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()[:16]
        result["estimate_id"] = estimate_id
        result["market_yield_proposal"] = crop_estimation.market_yield_proposal(result, estimate_id=estimate_id)
    return result


# ---------------------------------------------------------------------------
# Authorized asset retrieval / deletion
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _parse_range_header(range_header: str | None) -> tuple[int | None, int | None] | None:
    """Parse ``bytes=start-end`` / ``bytes=start-`` / ``bytes=-suffix``.

    Returns ``None`` (serve the full object) for absent or syntactically
    invalid headers, per RFC 9110 §14.2 (an unparseable Range is ignored).
    """
    if not range_header:
        return None
    match = _RANGE_RE.fullmatch(range_header.strip())
    if not match:
        return None
    start_raw, end_raw = match.group(1), match.group(2)
    if not start_raw and not end_raw:
        return None
    if not start_raw:
        return (None, int(end_raw))  # suffix: last N bytes
    return (int(start_raw), int(end_raw) if end_raw else None)


@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    range_spec = _parse_range_header(range_header)
    asset, iterator, total, served = svc.open_asset_stream(db, ctx, asset_id, range_spec=range_spec)
    filename = _sanitize_filename(asset.filename or asset.id)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "Accept-Ranges": "bytes",
    }
    status_code = status.HTTP_200_OK
    if served is not None:
        start, end, size = served
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        status_code = status.HTTP_206_PARTIAL_CONTENT
    elif total:
        headers["Content-Length"] = str(total)
    return StreamingResponse(
        iterator, status_code=status_code,
        media_type=asset.content_type or "application/octet-stream", headers=headers,
    )


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    svc.delete_asset(db, ctx, asset_id)
    return {"status": "deleted", "asset_id": asset_id}


def _content_matches_kind(kind: str, head: bytes, content_type: str | None) -> bool:
    if kind == "file":
        # Generic attachments are size-bounded + hashed, but still reject the
        # obviously-dangerous archive/executable signatures.
        return head[:2] not in (b"MZ",) and head[:4] != b"\x7fELF"
    if head[:5] in (b"PK\x03\x04", b"%PDF-") or head[:1] in (b"{", b"["):
        return False  # reject document/text payloads masquerading as media
    # Media must present a recognized container signature — never trust the
    # declared MIME type alone.
    magics = _KIND_MAGIC.get(kind, [])
    return any(head.startswith(magic) or magic in head[:16] for magic in magics)


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

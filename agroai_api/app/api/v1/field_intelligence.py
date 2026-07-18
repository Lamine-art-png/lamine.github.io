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
from datetime import datetime
from typing import Literal

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.services import field_intelligence as svc

router = APIRouter(prefix="/field-intelligence", tags=["field-intelligence"])

_KIND_MAGIC: dict[str, list[bytes]] = {
    "audio": [b"OggS", b"ID3", b"RIFF", b"\x1aE\xdf\xa3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
    "video": [b"\x1aE\xdf\xa3", b"ftyp", b"RIFF"],
    "photo": [b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF"],
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


class CaptureInitiateRequest(BaseModel):
    client_capture_id: str = Field(max_length=_MAX_NAME)
    idempotency_key: str | None = Field(default=None, max_length=_MAX_NAME)
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
    asset_manifest: list[dict] = Field(default_factory=list, max_length=25)
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


class CaptureCompleteRequest(BaseModel):
    corrected_transcript: str | None = Field(default=None, max_length=_MAX_TEXT)
    language: str | None = Field(default="en", max_length=16)


class SyncBatchRequest(BaseModel):
    captures: list[dict] = Field(min_length=1)


class ObservationPatchRequest(BaseModel):
    corrected_transcript: str | None = Field(default=None, max_length=_MAX_TEXT)
    field_id: str | None = Field(default=None, max_length=_MAX_NAME)
    field_name: str | None = Field(default=None, max_length=_MAX_NAME)
    block_id: str | None = Field(default=None, max_length=_MAX_NAME)
    block_name: str | None = Field(default=None, max_length=_MAX_NAME)
    crop: str | None = Field(default=None, max_length=_MAX_NAME)
    event_type: str | None = Field(default=None, max_length=64)
    severity: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    structured: dict | None = None


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

@router.post("/captures/initiate")
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
        if kind == "audio" and duration_seconds and duration_seconds > settings.FIELD_AUDIO_MAX_SECONDS:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio exceeds duration limit")
        if not _content_matches_kind(kind, head, file.content_type):
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Content does not match declared media type")

        asset = svc.register_asset(
            db, ctx, capture_id,
            client_asset_id=client_asset_id, kind=kind, content_type=file.content_type,
            filename=file.filename, content_sha256=digest.hexdigest(), size_bytes=total,
            duration_seconds=duration_seconds, spool_path=spool_path,
        )
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
    return {"status": "ok", "capture": svc.serialize_capture(session)}


@router.post("/sync/batch")
def sync_batch(
    payload: SyncBatchRequest,
    background: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    if len(payload.captures) > int(settings.FIELD_SYNC_MAX_BATCH):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Sync batch too large")
    result = svc.sync_batch(db, ctx, payload.captures)
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
# Authorized asset retrieval / deletion
# ---------------------------------------------------------------------------

@router.get("/assets/{asset_id}/content")
def get_asset_content(
    asset_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    asset, data = svc.read_asset_bytes(db, ctx, asset_id)
    filename = (asset.filename or asset.id).replace('"', "")
    return Response(
        content=data,
        media_type=asset.content_type or "application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
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
        return True  # generic attachments allowed; still size-bounded + hashed
    if head[:5] in (b"PK\x03\x04", b"%PDF-") or head[:1] in (b"{", b"["):
        return False  # reject document/text payloads masquerading as media
    magics = _KIND_MAGIC.get(kind, [])
    if any(head.startswith(magic) or magic in head[:16] for magic in magics):
        return True
    declared = (content_type or "").lower()
    prefix = {"audio": "audio/", "video": "video/", "photo": "image/"}.get(kind, "")
    return bool(prefix and declared.startswith(prefix))


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

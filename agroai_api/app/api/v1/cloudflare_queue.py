from __future__ import annotations

import asyncio
import hmac
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.services.connector_object_gc import run_connector_object_gc
from app.services.object_storage_probe import probe_object_storage
from app.services.production_readiness import evaluate_production_readiness
from app.services.redis_task_queue import queue_configured
from app.services.release_contract import evaluate_release_contract
from app.services.task_outbox_service import drain_pending_outbox
from app.platform_api.webhook_delivery import WEBHOOK_TASK_TYPE, publish_pending_webhook_outbox


router = APIRouter(tags=["internal-connector-queue"])
QUEUE_CONTRACT = "cloudflare-queue-v1"
RELEASE_CONTRACT = "agroai-release-v1"
_TERMINAL = {"succeeded", "failed", "cancelled", "delivered", "disabled"}
_TRANSIENT = {"retrying", "deferred", "queued", "running"}


class ConnectorTaskDelivery(BaseModel):
    job_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    task_type: str = Field(min_length=1, max_length=256)
    enqueued_at: str | None = Field(default=None, max_length=128)
    attempt: int | None = Field(default=None, ge=0, le=1000)


def process_connector_task(**kwargs):
    from app.services.connector_task_processor import process_connector_task as implementation

    return implementation(**kwargs)


def _configured_queue_tokens() -> tuple[str, ...]:
    values = (
        getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "").strip(),
        os.getenv("CLOUDFLARE_QUEUE_CONSUMER_TOKEN_PREVIOUS", "").strip(),
    )
    return tuple(value for value in values if value)


def _require_queue_token(authorization: str | None = Header(default=None)) -> None:
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    configured = _configured_queue_tokens()
    if not supplied or not configured or not any(hmac.compare_digest(candidate, supplied) for candidate in configured):
        raise HTTPException(status_code=401, detail="Unauthorized queue delivery")


@router.get("/internal/queue/health", dependencies=[Depends(_require_queue_token)])
async def queue_contract_health() -> dict:
    ready = queue_configured()
    if not ready:
        raise HTTPException(
            status_code=503,
            detail={"error": "durable_connector_queue_not_configured", "contract": QUEUE_CONTRACT},
        )
    return {"status": "ok", "contract": QUEUE_CONTRACT, "queue_configured": True}


@router.get("/internal/release/health", dependencies=[Depends(_require_queue_token)])
async def release_contract_health(db: Session = Depends(get_db)) -> dict:
    try:
        report = evaluate_release_contract(db)
        storage = await asyncio.to_thread(probe_object_storage)
        production = evaluate_production_readiness(settings).to_dict()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "release_contract_evaluation_failed",
                "contract": RELEASE_CONTRACT,
                "reason": exc.__class__.__name__,
            },
        ) from exc
    payload = {
        "contract": RELEASE_CONTRACT,
        **report,
        "object_storage_configured": bool(storage.get("configured")),
        "object_storage_reachable": bool(storage.get("reachable")),
        "production_ready": bool(production.get("ready")),
        "production_blocker_codes": [item.get("code") for item in production.get("blockers", [])],
        "platform_api_enabled": bool(getattr(settings, "PLATFORM_API_ENABLED", False)),
    }
    if (
        report["status"] != "ok"
        or not storage.get("configured")
        or not storage.get("reachable")
        or not production.get("ready")
    ):
        payload["status"] = "blocked"
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.post("/internal/queue/connector-task", dependencies=[Depends(_require_queue_token)])
async def deliver_connector_task(payload: ConnectorTaskDelivery) -> dict:
    worker_id = f"cloudflare-queue:{uuid.uuid4().hex[:16]}"
    try:
        status = await asyncio.to_thread(
            process_connector_task,
            job_id=payload.job_id,
            tenant_id=payload.tenant_id,
            task_type=payload.task_type,
            worker_id=worker_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "connector_task_processing_unavailable", "reason": exc.__class__.__name__},
        ) from exc
    if status in _TERMINAL:
        return {"status": status, "job_id": payload.job_id, "terminal": True}
    if payload.task_type == WEBHOOK_TASK_TYPE and status == "retrying":
        return {"status": status, "job_id": payload.job_id, "terminal": True, "durable_retry_scheduled": True}
    if status in _TRANSIENT:
        raise HTTPException(
            status_code=503,
            detail={"error": "connector_task_retry_required", "status": status, "job_id": payload.job_id},
        )
    raise HTTPException(
        status_code=503,
        detail={"error": "connector_task_unknown_status", "status": status, "job_id": payload.job_id},
    )


@router.post("/internal/queue/drain-outbox", dependencies=[Depends(_require_queue_token)])
async def drain_task_outbox() -> dict:
    if not queue_configured():
        raise HTTPException(status_code=503, detail="Durable connector queue is not configured")
    try:
        outbox = await asyncio.to_thread(drain_pending_outbox, limit=100)
        webhook_outbox = await asyncio.to_thread(_drain_webhook_outbox)
        object_gc = await asyncio.to_thread(run_connector_object_gc, limit=50)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "scheduled_maintenance_failed", "reason": exc.__class__.__name__},
        ) from exc
    return {"status": "ok", "outbox": outbox, "webhook_outbox": webhook_outbox, "object_gc": object_gc}


def _drain_webhook_outbox() -> dict[str, int]:
    db = SessionLocal()
    try:
        return publish_pending_webhook_outbox(db, limit=100)
    finally:
        db.close()


@router.post("/internal/queue/maintenance", dependencies=[Depends(_require_queue_token)])
async def run_queue_maintenance() -> dict:
    return await drain_task_outbox()

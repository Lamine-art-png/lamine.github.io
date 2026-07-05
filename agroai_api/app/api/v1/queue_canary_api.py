import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.cloudflare_queue import _require_queue_token
from app.db.base import get_db
from app.services.connector_task_processor import create_queue_canary_job, read_queue_canary_job
from app.services.redis_task_queue import queue_configured
from app.services.task_outbox_service import drain_pending_outbox


router = APIRouter(tags=["internal-queue-canary"])


@router.post("/internal/queue/canary", status_code=202, dependencies=[Depends(_require_queue_token)])
async def create_canary(db: Session = Depends(get_db)) -> dict:
    if not queue_configured():
        raise HTTPException(status_code=503, detail="Durable connector queue is not configured")
    job = create_queue_canary_job(db)
    publication = await asyncio.to_thread(drain_pending_outbox, limit=25)
    return {"status": "queued", "job_id": job.id, "queue_publication": publication}


@router.get("/internal/queue/canary/{job_id}", dependencies=[Depends(_require_queue_token)])
def read_canary(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = read_queue_canary_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Queue canary not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
        "output": dict(job.output_json or {}),
    }

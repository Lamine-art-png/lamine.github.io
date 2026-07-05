from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid

from app.core.config import settings
from app.db.base import SessionLocal
from app.services.connector_task_processor import process_connector_task
from app.services.redis_task_queue import QueueMessage, get_task_queue
from app.services.task_outbox_service import publish_pending_outbox


logger = logging.getLogger(__name__)
_STOP = False


def _stop(*_args) -> None:
    global _STOP
    _STOP = True


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _handle(message: QueueMessage, *, worker_id: str) -> str:
    return process_connector_task(
        job_id=message.job_id,
        tenant_id=message.tenant_id,
        task_type=message.task_type,
        worker_id=worker_id,
    )


def _publish_outbox() -> None:
    db = SessionLocal()
    try:
        publish_pending_outbox(db, limit=100)
    except Exception:
        db.rollback()
        logger.exception("task outbox publication failed")
    finally:
        db.close()


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = _worker_id()
    queue = get_task_queue()
    queue.ensure_group()
    if not queue.ping():
        raise RuntimeError("Redis task queue is unavailable")
    lease_ms = int(getattr(settings, "TASK_QUEUE_LEASE_SECONDS", 120) or 120) * 1000
    block_ms = int(getattr(settings, "TASK_QUEUE_BLOCK_MS", 5000) or 5000)
    logger.info("connector worker started worker_id=%s", worker_id)

    while not _STOP:
        _publish_outbox()
        messages = queue.claim_stale(worker_id, min_idle_ms=lease_ms)
        if not messages:
            messages = queue.read(worker_id, block_ms=block_ms)
        if not messages:
            continue
        for message in messages:
            if _STOP:
                break
            try:
                status = _handle(message, worker_id=worker_id)
            except Exception:
                logger.exception("worker crashed while handling job_id=%s", message.job_id)
                status = "retrying"
            if status in {"succeeded", "failed", "cancelled"}:
                queue.ack(message.message_id)
            elif status == "deferred":
                time.sleep(0.1)
    logger.info("connector worker stopped worker_id=%s", worker_id)


if __name__ == "__main__":
    logging.basicConfig(level=getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO))
    run_forever()

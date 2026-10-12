"""Atomic per-organization daily frame budget for specialized detection.

Detector frames cost money, so the daily budget is enforced with a
reservation taken before any frame is sent:

* a transaction-scoped PostgreSQL advisory lock keyed by organization
  serializes reservations, so concurrent workers for the same organization
  take turns. (A row lock on ``organizations`` would self-deadlock: the
  pipeline's own inserts that reference the organization hold ``FOR KEY
  SHARE`` on that row, which ``FOR UPDATE`` waits for.);
* frames already used today are counted from detection runs: a run still
  ``reserved`` counts its reserved frames (the worker crashed, or its
  pipeline rolled back before recording what it sent), a finished run counts
  the frames it actually sent;
* a ``reserved`` detection run for the granted frames is inserted and
  committed before the lock is released.

On PostgreSQL the reservation runs in its own short transaction on a
separate session, so it is durable before the first frame is sent and the
pipeline's own transaction is not committed early. SQLite (tests and local
development, a single writer) records it in the pipeline transaction.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.field_intelligence import FieldObservationProcessingRun

DETECTION_STAGE = "detection"
RESERVED_STATUS = "reserved"


def frames_used_today(db: Session, tenant_id: str, *, now: datetime | None = None) -> int:
    """Frames reserved or sent for this organization since 00:00 UTC."""
    midnight = (now or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(FieldObservationProcessingRun.status, FieldObservationProcessingRun.output_json)
        .filter(FieldObservationProcessingRun.tenant_id == tenant_id)
        .filter(FieldObservationProcessingRun.stage == DETECTION_STAGE)
        .filter(FieldObservationProcessingRun.created_at >= midnight)
        .all()
    )
    used = 0
    for status, output in rows:
        output = output or {}
        key = "frames_reserved" if status == RESERVED_STATUS else "frames_sent"
        used += int(output.get(key) or 0)
    return used


def _budget_lock_key(tenant_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f"field-detection-budget:{tenant_id}".encode("utf-8")).digest()[:8], "big", signed=True)


def _reserve(db: Session, observation: Any, *, requested: int, daily_budget: int, provider: str, attempt: int,
             lock: bool) -> tuple[str | None, int, int]:
    if lock:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _budget_lock_key(observation.tenant_id)})
    used = frames_used_today(db, observation.tenant_id)
    granted = max(0, min(int(requested), int(daily_budget) - used))
    if granted == 0:
        return None, 0, used
    run = FieldObservationProcessingRun(
        id=str(uuid.uuid4()),
        tenant_id=observation.tenant_id,
        workspace_id=getattr(observation, "workspace_id", None),
        observation_id=getattr(observation, "id", None),
        capture_session_id=getattr(observation, "capture_session_id", None),
        stage=DETECTION_STAGE,
        provider=provider,
        status=RESERVED_STATUS,
        attempt_count=attempt,
        input_json={"frames_requested": int(requested), "daily_budget": int(daily_budget), "used_before": used},
        output_json={"frames_reserved": granted, "frames_sent": 0},
    )
    db.add(run)
    return run.id, granted, used


def reserve_frames(
    db: Session, observation: Any, *, requested: int, daily_budget: int, provider: str, attempt: int = 1,
) -> tuple[str | None, int, int]:
    """Reserve up to ``requested`` frames; returns ``(run_id, granted, used_before)``.

    ``run_id`` is None when nothing was granted. The caller sends at most
    ``granted`` frames and then records what it sent on that run.
    """
    if requested <= 0:
        return None, 0, 0
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        result = _reserve(db, observation, requested=requested, daily_budget=daily_budget, provider=provider,
                          attempt=attempt, lock=False)
        db.flush()
        return result
    with Session(bind=bind) as quota_db:
        with quota_db.begin():
            return _reserve(quota_db, observation, requested=requested, daily_budget=daily_budget, provider=provider,
                            attempt=attempt, lock=True)

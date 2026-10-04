"""Intelligence sessions: bounded application state across runs.

A session is not a chat-log dump. It holds:

* ``context``: pinned agricultural context the application sets explicitly
  (same shape as the request ``context``), merged under each request's own
  context, and
* a bounded window of prior turns (question + answer summary) written by
  AGRO-AI only when a run completes successfully.

Limits: 200 stored turns per session (oldest pruned), the latest 8 turns are
sent to inference, each stored turn is truncated to 4,000 characters, and a
session expires after ``retention_days`` (1-90, default 30) of inactivity.
Deleting a session hard-deletes its turns immediately.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.intelligence_platform.contract import AgriculturalContext, validate_metadata
from app.intelligence_platform.ownership import owned
from app.models.intelligence_platform import IntelligenceSession, IntelligenceSessionTurn
from app.platform_api.principal import PlatformPrincipal


MAX_STORED_TURNS = 200
HISTORY_TURNS = 8
MAX_TURN_CHARS = 4_000
MAX_ACTIVE_SESSIONS_PER_PROJECT = 10_000


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    context: AgriculturalContext | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    retention_days: int = Field(default=30, ge=1, le=90)

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_metadata(value)


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    context: AgriculturalContext | None = None
    metadata: dict[str, str] | None = None

    @field_validator("metadata")
    @classmethod
    def safe_metadata(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return validate_metadata(value) if value is not None else value


def _query(db: Session, principal: PlatformPrincipal):
    return owned(db.query(IntelligenceSession), IntelligenceSession, principal)


def create_session(db: Session, principal: PlatformPrincipal, payload: SessionCreate) -> IntelligenceSession:
    # Quota is per project by design: deliberately not workspace-scoped.
    active = (
        db.query(IntelligenceSession)
        .filter(
            IntelligenceSession.organization_id == principal.organization_id,
            IntelligenceSession.api_project_id == principal.api_project_id,
            IntelligenceSession.status == "active",
        )
        .count()
    )
    if active >= MAX_ACTIVE_SESSIONS_PER_PROJECT:
        raise HTTPException(status_code=409, detail={"code": "session_quota_exceeded"})
    now = datetime.utcnow()
    row = IntelligenceSession(
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        workspace_id=principal.workspace_id,
        created_by_api_key_id=principal.api_key_id,
        created_by_user_id=principal.user_id,
        title=payload.title,
        context_json=payload.context.model_dump(mode="json", exclude_none=True) if payload.context else {},
        metadata_json=payload.metadata,
        status="active",
        turn_count=0,
        retention_days=payload.retention_days,
        expires_at=now + timedelta(days=payload.retention_days),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    return row


def owned_session(
    db: Session,
    principal: PlatformPrincipal,
    session_id: str,
    *,
    for_update: bool = False,
) -> IntelligenceSession:
    query = _query(db, principal).filter(IntelligenceSession.id == session_id)
    if for_update:
        query = query.with_for_update().populate_existing()
    row = query.first()
    if row is None or row.status != "active" or row.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=404, detail={"code": "session_not_found"})
    return row


def update_session(db: Session, principal: PlatformPrincipal, session_id: str, payload: SessionUpdate) -> IntelligenceSession:
    row = owned_session(db, principal, session_id, for_update=True)
    if payload.title is not None:
        row.title = payload.title
    if payload.context is not None:
        row.context_json = payload.context.model_dump(mode="json", exclude_none=True)
    if payload.metadata is not None:
        row.metadata_json = payload.metadata
    row.updated_at = datetime.utcnow()
    db.commit()
    return row


def delete_session(db: Session, principal: PlatformPrincipal, session_id: str) -> None:
    row = owned_session(db, principal, session_id, for_update=True)
    db.query(IntelligenceSessionTurn).filter(
        IntelligenceSessionTurn.session_id == row.id,
        IntelligenceSessionTurn.organization_id == principal.organization_id,
    ).delete(synchronize_session=False)
    row.status = "deleted"
    row.deleted_at = datetime.utcnow()
    row.context_json = {}
    row.metadata_json = {}
    row.title = None
    row.turn_count = 0
    db.commit()


def history(db: Session, session: IntelligenceSession) -> list[dict[str, str]]:
    rows = (
        db.query(IntelligenceSessionTurn)
        .filter(
            IntelligenceSessionTurn.session_id == session.id,
            IntelligenceSessionTurn.organization_id == session.organization_id,
        )
        .order_by(IntelligenceSessionTurn.created_at.desc(), IntelligenceSessionTurn.id.desc())
        # Each stored row (user or assistant) is one turn; the contract is the
        # latest HISTORY_TURNS turns, exactly.
        .limit(HISTORY_TURNS)
        .all()
    )
    return [{"role": row.role, "content": row.content} for row in reversed(rows)]


def turns(db: Session, principal: PlatformPrincipal, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    session = owned_session(db, principal, session_id)
    rows = (
        db.query(IntelligenceSessionTurn)
        .filter(
            IntelligenceSessionTurn.session_id == session.id,
            IntelligenceSessionTurn.organization_id == principal.organization_id,
        )
        .order_by(IntelligenceSessionTurn.created_at.desc(), IntelligenceSessionTurn.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        {"id": row.id, "role": row.role, "content": row.content, "run_id": row.run_id,
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]


def append_turns(
    db: Session,
    *,
    session_id: str,
    organization_id: str,
    api_project_id: str,
    run_id: str,
    question: str,
    answer: str,
) -> int | None:
    """Append one completed exchange inside the caller's transaction.

    Locks the session row so concurrent completions keep an exact count and
    pruning never races. Returns the new turn count, or None when the session
    was deleted or expired while the run was computing (nothing is written).
    """
    session = (
        db.query(IntelligenceSession)
        .filter(
            IntelligenceSession.id == session_id,
            IntelligenceSession.organization_id == organization_id,
            IntelligenceSession.api_project_id == api_project_id,
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    now = datetime.utcnow()
    if session is None or session.status != "active" or session.expires_at <= now:
        return None
    for role, content in (("user", question), ("assistant", answer)):
        db.add(
            IntelligenceSessionTurn(
                session_id=session.id,
                organization_id=organization_id,
                api_project_id=api_project_id,
                run_id=run_id,
                role=role,
                content=str(content or "")[:MAX_TURN_CHARS],
                created_at=now,
            )
        )
        now = now + timedelta(microseconds=1)
    session.turn_count = int(session.turn_count or 0) + 2
    db.flush()
    if session.turn_count > MAX_STORED_TURNS:
        overflow = session.turn_count - MAX_STORED_TURNS
        stale_ids = [
            row.id
            for row in db.query(IntelligenceSessionTurn.id)
            .filter(IntelligenceSessionTurn.session_id == session.id)
            .order_by(IntelligenceSessionTurn.created_at.asc(), IntelligenceSessionTurn.id.asc())
            .limit(overflow)
            .all()
        ]
        if stale_ids:
            db.query(IntelligenceSessionTurn).filter(IntelligenceSessionTurn.id.in_(stale_ids)).delete(synchronize_session=False)
        session.turn_count = MAX_STORED_TURNS
    session.last_used_at = now
    session.expires_at = now + timedelta(days=int(session.retention_days or 30))
    session.updated_at = now
    return int(session.turn_count)


def expire_sessions(db: Session, *, limit: int = 200) -> int:
    rows = (
        db.query(IntelligenceSession)
        .filter(IntelligenceSession.status == "active", IntelligenceSession.expires_at <= datetime.utcnow())
        .order_by(IntelligenceSession.expires_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    for row in rows:
        db.query(IntelligenceSessionTurn).filter(IntelligenceSessionTurn.session_id == row.id).delete(synchronize_session=False)
        row.status = "expired"
        row.context_json = {}
        row.metadata_json = {}
        row.turn_count = 0
        row.deleted_at = datetime.utcnow()
    db.commit()
    return len(rows)


def public_session(row: IntelligenceSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "object": "agroai.intelligence.session",
        "title": row.title,
        "context": dict(row.context_json or {}),
        "metadata": dict(row.metadata_json or {}),
        "status": row.status,
        "turn_count": int(row.turn_count or 0),
        "retention_days": int(row.retention_days or 30),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

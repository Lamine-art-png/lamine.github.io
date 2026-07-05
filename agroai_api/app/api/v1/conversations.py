"""Persistent Ask AGRO-AI conversation history.

This API gives the portal a ChatGPT-like memory layer: server-side chat
threads, messages, navigation, and safe tenant/workspace scoping. It deliberately
stores only user/assistant text plus non-secret metadata/artifact references.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context, require_workspace_access
from app.db.base import get_db
from app.models.saas import Conversation, ConversationMessage

router = APIRouter(tags=["conversations"])

TABLES = [Conversation.__table__, ConversationMessage.__table__]


def verify_conversation_schema(db: Session) -> None:
    """Verify Alembic-owned conversation tables without mutating schema."""
    bind = db.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    missing: dict[str, list[str]] = {}
    for table in TABLES:
        if table.name not in tables:
            missing[table.name] = sorted(column.name for column in table.columns)
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = {column.name for column in table.columns} - existing
        if missing_columns:
            missing[table.name] = sorted(missing_columns)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "conversation_schema_not_ready", "missing": missing, "action": "run_alembic_upgrade_head"},
        )


class ConversationCreateRequest(BaseModel):
    title: str | None = None
    workspace_id: str | None = None
    message: str | None = None


class ConversationPatchRequest(BaseModel):
    title: str | None = None
    status: Literal["open", "archived", "deleted"] | None = None


class ConversationMessageRequest(BaseModel):
    content: str
    audience: str | None = None
    output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _tenant_id(auth: AuthContext) -> str:
    if not auth.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return auth.organization.id


def _verify_workspace(db: Session, auth: AuthContext, workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    workspace, _membership = require_workspace_access(workspace_id, auth.user, db)
    tenant_id = _tenant_id(auth)
    if workspace.organization_id != tenant_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace.id


def _title_from_message(text: str) -> str:
    clean = " ".join((text or "").strip().split())
    if not clean:
        return "New chat"
    return clean[:64] + ("…" if len(clean) > 64 else "")


def _conversation_query(db: Session, auth: AuthContext):
    return db.query(Conversation).filter(
        Conversation.organization_id == _tenant_id(auth),
        Conversation.user_id == auth.user.id,
        Conversation.status != "deleted",
    )


def _message_count(db: Session, conversation_id: str) -> int:
    return db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count()


def message_public(row: ConversationMessage) -> dict[str, Any]:
    metadata = row.artifacts_json or {}
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "content": row.content,
        "metadata_json": metadata,
        "artifact": metadata.get("artifact"),
        "uploaded_evidence": metadata.get("uploaded_evidence", []),
        "agentic_actions": metadata.get("agentic_actions", []),
        "question": metadata.get("question"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def conversation_public(db: Session, row: Conversation, include_preview: bool = True) -> dict[str, Any]:
    preview = None
    if include_preview:
        latest = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == row.id)
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        preview = latest.content[:180] if latest else None
    return {
        "id": row.id,
        "title": row.title or "New chat",
        "workspace_id": row.workspace_id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "status": row.status,
        "message_count": _message_count(db, row.id),
        "preview": preview,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get_conversation(db: Session, auth: AuthContext, conversation_id: str) -> Conversation:
    verify_conversation_schema(db)
    row = db.get(Conversation, conversation_id)
    if not row or row.organization_id != _tenant_id(auth) or row.user_id != auth.user.id or row.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


@router.get("/conversations")
def list_conversations(
    workspace_id: str | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=100),
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    verify_conversation_schema(db)
    workspace_id = _verify_workspace(db, auth, workspace_id)
    query = _conversation_query(db, auth)
    if workspace_id:
        query = query.filter(Conversation.workspace_id == workspace_id)
    rows = query.order_by(Conversation.updated_at.desc()).limit(limit).all()
    return {"status": "ok", "conversations": [conversation_public(db, row) for row in rows]}


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreateRequest, auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_conversation_schema(db)
    workspace_id = _verify_workspace(db, auth, payload.workspace_id)
    title = payload.title or _title_from_message(payload.message or "")
    row = Conversation(
        organization_id=_tenant_id(auth),
        workspace_id=workspace_id,
        user_id=auth.user.id,
        title=title or "New chat",
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "created", "conversation": conversation_public(db, row, include_preview=False)}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_conversation(db, auth, conversation_id)
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == row.id)
        .order_by(ConversationMessage.created_at.asc())
        .limit(300)
        .all()
    )
    return {"status": "ok", "conversation": conversation_public(db, row), "messages": [message_public(message) for message in messages]}


@router.patch("/conversations/{conversation_id}")
def patch_conversation(conversation_id: str, payload: ConversationPatchRequest, auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_conversation(db, auth, conversation_id)
    if payload.title is not None:
        row.title = _title_from_message(payload.title)
    if payload.status is not None:
        row.status = payload.status
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"status": "ok", "conversation": conversation_public(db, row)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_conversation(db, auth, conversation_id)
    row.status = "deleted"
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/messages")
def add_message(conversation_id: str, payload: ConversationMessageRequest, auth: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_conversation(db, auth, conversation_id)
    now = datetime.utcnow()
    user_message = ConversationMessage(
        conversation_id=row.id,
        organization_id=row.organization_id,
        user_id=auth.user.id,
        role="user",
        content=payload.content,
        artifacts_json={"audience": payload.audience, "uploaded_evidence": payload.metadata.get("uploaded_evidence", [])},
        citations_json=[],
        missing_data_json=[],
        recommended_actions_json=[],
    )
    db.add(user_message)
    assistant_message = None
    if payload.output is not None:
        assistant_metadata = dict(payload.metadata or {})
        assistant_metadata.setdefault("question", payload.content)
        assistant_message = ConversationMessage(
            conversation_id=row.id,
            organization_id=row.organization_id,
            user_id=auth.user.id,
            role="assistant",
            content=payload.output,
            artifacts_json=assistant_metadata,
            citations_json=assistant_metadata.get("citations", []),
            missing_data_json=assistant_metadata.get("missing_data", []),
            recommended_actions_json=assistant_metadata.get("agentic_actions", []),
        )
        db.add(assistant_message)

    if not row.title or row.title == "New chat" or row.title.startswith("Ask AGRO-AI"):
        row.title = _title_from_message(payload.content)
    row.updated_at = now
    db.commit()
    db.refresh(row)
    db.refresh(user_message)
    if assistant_message:
        db.refresh(assistant_message)

    messages = [message_public(user_message)]
    if assistant_message:
        messages.append(message_public(assistant_message))
    return {"status": "stored", "conversation": conversation_public(db, row), "messages": messages}

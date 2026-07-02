from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db

router = APIRouter(tags=["preferences"])


class PortalPreferencesUpdate(BaseModel):
    locale: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    notifications: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


def _ensure_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id VARCHAR PRIMARY KEY,
            locale VARCHAR,
            timezone VARCHAR,
            notifications_json TEXT,
            ui_json TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
    """))
    db.commit()


def _decode(value: Any, fallback: dict | None = None) -> dict:
    if not value:
        return fallback or {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else (fallback or {})
    except Exception:
        return fallback or {}


def _row_to_payload(row: Any | None, ctx: AuthContext) -> dict:
    if row is None:
        return {
            "locale": "auto",
            "timezone": "auto",
            "notifications": {
                "report_delivery": True,
                "operational_alerts": True,
                "support_updates": True,
                "billing_updates": True,
            },
            "ui": {"density": "comfortable", "assistant_speed": "balanced"},
            "user": {"id": ctx.user.id, "name": ctx.user.name, "email": ctx.user.email},
        }
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "locale": mapping.get("locale") or "auto",
        "timezone": mapping.get("timezone") or "auto",
        "notifications": _decode(mapping.get("notifications_json"), {"report_delivery": True, "operational_alerts": True, "support_updates": True, "billing_updates": True}),
        "ui": _decode(mapping.get("ui_json"), {"density": "comfortable", "assistant_speed": "balanced"}),
        "user": {"id": ctx.user.id, "name": ctx.user.name, "email": ctx.user.email},
        "updated_at": mapping.get("updated_at"),
    }


@router.get("/account/preferences")
def get_preferences(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    _ensure_table(db)
    row = db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": ctx.user.id}).first()
    return {"preferences": _row_to_payload(row, ctx)}


@router.patch("/account/preferences")
def update_preferences(payload: PortalPreferencesUpdate, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    _ensure_table(db)
    current = db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": ctx.user.id}).first()
    merged = _row_to_payload(current, ctx)
    if payload.locale is not None:
        merged["locale"] = payload.locale.strip() or "auto"
    if payload.timezone is not None:
        merged["timezone"] = payload.timezone.strip() or "auto"
    if payload.notifications is not None:
        merged["notifications"] = {**merged.get("notifications", {}), **payload.notifications}
    if payload.ui is not None:
        merged["ui"] = {**merged.get("ui", {}), **payload.ui}
    now = datetime.utcnow().isoformat(timespec="seconds")
    db.execute(text("""
        INSERT INTO user_preferences (user_id, locale, timezone, notifications_json, ui_json, created_at, updated_at)
        VALUES (:user_id, :locale, :timezone, :notifications_json, :ui_json, :created_at, :updated_at)
        ON CONFLICT(user_id) DO UPDATE SET
            locale = excluded.locale,
            timezone = excluded.timezone,
            notifications_json = excluded.notifications_json,
            ui_json = excluded.ui_json,
            updated_at = excluded.updated_at
    """), {
        "user_id": ctx.user.id,
        "locale": merged["locale"],
        "timezone": merged["timezone"],
        "notifications_json": json.dumps(merged["notifications"]),
        "ui_json": json.dumps(merged["ui"]),
        "created_at": now,
        "updated_at": now,
    })
    db.commit()
    row = db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": ctx.user.id}).first()
    return {"preferences": _row_to_payload(row, ctx), "message": "Preferences saved."}

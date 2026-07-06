from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.services.language_registry import enabled_ui_locales, locale_specs, normalize_bcp47

router = APIRouter(tags=["preferences"])


class PortalPreferencesUpdate(BaseModel):
    locale: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    notifications: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


def _verify_table(db: Session) -> None:
    inspector = inspect(db.get_bind())
    if "user_preferences" not in set(inspector.get_table_names()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "preferences_schema_not_ready", "action": "run_alembic_upgrade_head"},
        )
    columns = {column["name"] for column in inspector.get_columns("user_preferences")}
    required = {"user_id", "locale", "timezone", "notifications_json", "ui_json", "created_at", "updated_at"}
    missing = required - columns
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "preferences_schema_not_ready", "missing": sorted(missing), "action": "run_alembic_upgrade_head"},
        )


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


def _canonical_ui_locale(value: str | None) -> str:
    raw = (value or "auto").strip().replace("_", "-") or "auto"
    enabled = {code.lower(): code for code in enabled_ui_locales()}
    exact = enabled.get(raw.lower())
    if exact:
        return exact

    normalized = normalize_bcp47(raw)
    exact = enabled.get(normalized.lower())
    if exact:
        return exact

    spec = locale_specs().get(normalized.lower()) or locale_specs().get(raw.lower())
    language_code = spec.language_code if spec else normalized.split("-", 1)[0].lower()
    for code in enabled_ui_locales():
        enabled_spec = locale_specs().get(code.lower())
        enabled_language = enabled_spec.language_code if enabled_spec else code.split("-", 1)[0].lower()
        if enabled_language == language_code:
            return code

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "unsupported_ui_locale", "locale": raw},
    )


def _row_to_payload(row: Any | None, ctx: AuthContext) -> dict:
    defaults = {
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
    if row is None:
        return defaults
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        **defaults,
        "locale": mapping.get("locale") or "auto",
        "timezone": mapping.get("timezone") or "auto",
        "notifications": _decode(mapping.get("notifications_json"), defaults["notifications"]),
        "ui": _decode(mapping.get("ui_json"), defaults["ui"]),
        "updated_at": mapping.get("updated_at"),
    }


def _get(ctx: AuthContext, db: Session) -> dict:
    _verify_table(db)
    row = db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": ctx.user.id}).first()
    return {"preferences": _row_to_payload(row, ctx)}


def _patch(payload: PortalPreferencesUpdate, ctx: AuthContext, db: Session) -> dict:
    _verify_table(db)
    current = db.execute(text("SELECT * FROM user_preferences WHERE user_id = :user_id"), {"user_id": ctx.user.id}).first()
    merged = _row_to_payload(current, ctx)
    if payload.locale is not None:
        merged["locale"] = _canonical_ui_locale(payload.locale)
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


@router.get("/account/preferences")
def get_account_preferences(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _get(ctx, db)


@router.patch("/account/preferences")
def update_account_preferences(payload: PortalPreferencesUpdate, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _patch(payload, ctx, db)


@router.get("/settings/preferences")
def get_settings_preferences(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _get(ctx, db)


@router.patch("/settings/preferences")
def update_settings_preferences(payload: PortalPreferencesUpdate, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    return _patch(payload, ctx, db)


from app.api.v1.i18n import router as i18n_router  # noqa: E402

router.include_router(i18n_router)

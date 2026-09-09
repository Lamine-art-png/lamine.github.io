from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings

_PURPOSE = b"agroai-agentic-plan-v1"
_TTL_SECONDS = 15 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _key() -> bytes:
    secret = str(getattr(settings, "SECRET_KEY", "") or "").strip()
    if not secret:
        raise RuntimeError("Application signing secret is unavailable")
    return hmac.new(_PURPOSE, secret.encode("utf-8"), hashlib.sha256).digest()


def sign_action_plan(
    *,
    organization_id: str,
    user_id: str,
    workspace_id: str | None,
    action: dict[str, Any],
) -> str:
    body = {
        "v": 1,
        "org": organization_id,
        "user": user_id,
        "workspace_id": workspace_id,
        "action_id": str(action.get("id") or ""),
        "action_type": str(action.get("action_type") or ""),
        "payload": action.get("payload") or {},
        "approval_required": bool(action.get("approval_required")),
        "title": str(action.get("title") or ""),
        "exp": int(time.time()) + _TTL_SECONDS,
    }
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    signature = hmac.new(_key(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(signature)}"


def verify_action_plan(
    token: str,
    *,
    organization_id: str,
    user_id: str,
) -> dict[str, Any]:
    try:
        raw_part, sig_part = str(token or "").split(".", 1)
        raw = _unb64(raw_part)
        supplied = _unb64(sig_part)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid action plan token") from exc
    expected = hmac.new(_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action plan signature mismatch")
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid action plan payload") from exc
    if body.get("org") != organization_id or body.get("user") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Action plan is not valid for this session")
    if int(body.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Action plan expired")
    if not str(body.get("action_type") or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Action plan has no action type")
    return body

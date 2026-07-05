from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.core.config import settings


def _urlsafe(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unurlsafe(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _secret() -> bytes:
    return settings.SECRET_KEY.encode("utf-8")


def sign_oauth_state(connection_id: str, *, purpose: str = "connector_oauth") -> str:
    payload = {
        "cid": connection_id,
        "iat": int(time.time()),
        "nonce": os.urandom(16).hex(),
        "purpose": purpose,
    }
    encoded = _urlsafe(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_oauth_state(state: str | None, *, max_age_seconds: int = 1800, purpose: str = "connector_oauth") -> dict[str, Any] | None:
    if not state or "." not in state:
        return None
    encoded, signature = state.rsplit(".", 1)
    expected = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        payload = json.loads(_unurlsafe(encoded))
    except Exception:
        return None
    if payload.get("purpose") != purpose:
        return None
    issued_at = int(payload.get("iat") or 0)
    if issued_at <= 0 or int(time.time()) - issued_at > max_age_seconds:
        return None
    if not payload.get("cid"):
        return None
    return payload

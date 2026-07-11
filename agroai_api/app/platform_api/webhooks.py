from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlparse

from app.platform_api.keys import _pepper


SAFE_WEBHOOK_EVENTS = {
    "connector.connected",
    "connector.degraded",
    "connector.revoked",
    "sync.started",
    "sync.completed",
    "sync.failed",
    "source.created",
    "observation.created",
    "field.updated",
    "recommendation.created",
    "action.approval_required",
    "action.completed",
    "action.failed",
}


def generate_webhook_secret() -> tuple[str, str, str]:
    plaintext = f"whsec_{secrets.token_urlsafe(32)}"
    digest = hmac.new(_pepper(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()
    return plaintext, digest, plaintext[:14]


def validate_webhook_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("webhook URL must be HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("webhook URL must not include embedded credentials")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise ValueError("webhook URL host is not allowed")
    return parsed.geturl()


def webhook_signature(secret: str, *, timestamp: str, event_id: str, payload: bytes) -> str:
    signed = b".".join([timestamp.encode("utf-8"), event_id.encode("utf-8"), payload])
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

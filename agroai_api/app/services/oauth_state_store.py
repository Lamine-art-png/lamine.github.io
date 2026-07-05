from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.connector_security import OAuthStateNonce
from app.models.operational_records import ConnectorConnection


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _signing_key() -> bytes:
    dedicated = os.getenv("OAUTH_STATE_SIGNING_KEY", "").strip()
    value = dedicated or settings.SECRET_KEY
    if not value:
        raise RuntimeError("OAuth state signing key is not configured")
    return value.encode("utf-8")


def _encode(payload: dict[str, Any]) -> str:
    encoded = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode(state: str | None) -> dict[str, Any] | None:
    if not state or "." not in state:
        return None
    encoded, signature = state.rsplit(".", 1)
    expected = hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        payload = json.loads(_b64d(encoded).decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def oauth_state_signing_is_dedicated() -> bool:
    return bool(os.getenv("OAUTH_STATE_SIGNING_KEY", "").strip())


def issue_oauth_state(
    db: Session,
    *,
    connection: ConnectorConnection,
    tenant_id: str,
    provider: str,
    redirect_url: str,
    purpose: str = "connector_oauth",
    ttl_seconds: int | None = None,
) -> str:
    if connection.tenant_id != tenant_id or connection.provider != provider:
        raise ValueError("OAuth state ownership mismatch")
    ttl = int(ttl_seconds or os.getenv("OAUTH_STATE_TTL_SECONDS", "900"))
    ttl = min(max(ttl, 60), 1800)
    now = datetime.utcnow()
    expires = now + timedelta(seconds=ttl)
    nonce = _b64e(os.urandom(24))
    redirect_hash = _digest(redirect_url.strip())
    payload = {
        "cid": connection.id,
        "tid": tenant_id,
        "provider": provider,
        "redirect_sha256": redirect_hash,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "nonce": nonce,
        "purpose": purpose,
    }
    db.add(
        OAuthStateNonce(
            tenant_id=tenant_id,
            connection_id=connection.id,
            provider=provider,
            purpose=purpose,
            nonce_hash=_digest(nonce),
            redirect_sha256=redirect_hash,
            issued_at=now,
            expires_at=expires,
            created_at=now,
        )
    )
    db.flush()
    return _encode(payload)


def consume_oauth_state(
    db: Session,
    *,
    state: str | None,
    redirect_url: str,
    purpose: str = "connector_oauth",
    max_future_skew_seconds: int = 60,
) -> dict[str, Any] | None:
    payload = _decode(state)
    if payload is None or payload.get("purpose") != purpose:
        return None
    required = ("cid", "tid", "provider", "redirect_sha256", "iat", "exp", "nonce")
    if any(payload.get(key) in (None, "") for key in required):
        return None
    now_epoch = int(time.time())
    try:
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (TypeError, ValueError):
        return None
    if issued_at > now_epoch + max_future_skew_seconds or expires_at < now_epoch or expires_at <= issued_at:
        return None
    redirect_hash = _digest(redirect_url.strip())
    if not hmac.compare_digest(str(payload["redirect_sha256"]), redirect_hash):
        return None

    connection = db.get(ConnectorConnection, str(payload["cid"]))
    if connection is None:
        return None
    if connection.tenant_id != str(payload["tid"]) or connection.provider != str(payload["provider"]):
        return None

    now = datetime.utcnow()
    statement = (
        update(OAuthStateNonce)
        .where(
            and_(
                OAuthStateNonce.connection_id == connection.id,
                OAuthStateNonce.tenant_id == connection.tenant_id,
                OAuthStateNonce.provider == connection.provider,
                OAuthStateNonce.purpose == purpose,
                OAuthStateNonce.nonce_hash == _digest(str(payload["nonce"])),
                OAuthStateNonce.redirect_sha256 == redirect_hash,
                OAuthStateNonce.consumed_at.is_(None),
                OAuthStateNonce.expires_at > now,
            )
        )
        .values(consumed_at=now)
    )
    result = db.execute(statement)
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return payload

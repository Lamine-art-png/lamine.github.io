from __future__ import annotations

import hashlib
import hmac
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import SecurityAuditEvent
from app.services.runtime_key_material import derive_runtime_key


def _privacy_key(purpose: str) -> bytes:
    try:
        return derive_runtime_key(f"security-audit:{purpose}")
    except RuntimeError:
        secret_key = str(getattr(settings, "SECRET_KEY", "") or "").strip()
        if secret_key:
            return hmac.new(
                b"agroai-security-audit-secret-key-root-v1",
                f"{purpose}\x00{secret_key}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
        webhook_secret = str(getattr(settings, "WEBHOOK_SECRET", "") or "").strip()
        if webhook_secret:
            return hmac.new(
                b"agroai-security-audit-webhook-secret-root-v1",
                f"{purpose}\x00{webhook_secret}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
        raise RuntimeError("security audit key material is not configured")


def privacy_hash(value: str | None, purpose: str) -> str | None:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    key = _privacy_key(purpose)
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def record_security_event(
    db: Session,
    *,
    event_type: str,
    outcome: str,
    organization_id: str | None = None,
    user_id: str | None = None,
    subject: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SecurityAuditEvent:
    event = SecurityAuditEvent(
        organization_id=organization_id,
        user_id=user_id,
        event_type=event_type,
        outcome=outcome,
        subject_hash=privacy_hash(subject, "subject"),
        ip_hash=privacy_hash(ip_address, "ip"),
        user_agent_hash=privacy_hash(user_agent, "user-agent"),
        metadata_json=metadata or {},
    )
    db.add(event)
    return event

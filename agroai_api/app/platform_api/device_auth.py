"""RFC 8628-style device authorization for the agroai CLI (first-party session).

Security properties:
  * device_code is high-entropy (secrets.token_urlsafe(32)) and is persisted
    only as an HMAC-SHA256 hash (peppered with SECRET_KEY); the plaintext is
    returned once to the CLI and never stored.
  * user_code is short, human-readable, unique and single-use.
  * short expiry; explicit human approval through an authenticated first-party
    browser session; organization binding recorded at approval time.
  * polling interval enforcement (slow_down) and replay protection: the token
    is minted exactly once, after which the row is marked ``consumed``.
  * no client secret is embedded in the CLI; no API key is used as human
    identity; the minted credential is a short-lived human control-plane JWT.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import PlatformCliDeviceAuthorization

DEVICE_CODE_TTL = timedelta(minutes=10)
DEFAULT_INTERVAL_SECONDS = 5
HUMAN_TOKEN_TTL = timedelta(hours=1)
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ23456789"  # unambiguous, no vowels


def _hash_device_code(device_code: str) -> str:
    pepper = str(getattr(settings, "SECRET_KEY", "dev") or "dev").encode("utf-8")
    return hmac.new(pepper, device_code.encode("utf-8"), hashlib.sha256).hexdigest()


def _new_user_code() -> str:
    body = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{body[:4]}-{body[4:]}"


def create_device_authorization(
    db: Session, *, requested_scope: str | None = None, client_label: str | None = None, now: datetime | None = None
) -> tuple[str, PlatformCliDeviceAuthorization]:
    moment = now or datetime.utcnow()
    device_code = secrets.token_urlsafe(32)
    # Ensure user_code uniqueness against outstanding challenges.
    for _ in range(10):
        user_code = _new_user_code()
        if not db.query(PlatformCliDeviceAuthorization).filter_by(user_code=user_code).first():
            break
    row = PlatformCliDeviceAuthorization(
        device_code_hash=_hash_device_code(device_code),
        user_code=user_code,
        status="pending",
        requested_scope=requested_scope,
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        client_label=(client_label or "agroai-cli")[:120],
        created_at=moment,
        expires_at=moment + DEVICE_CODE_TTL,
    )
    db.add(row)
    db.flush()
    db.commit()
    return device_code, row


def _lookup(db: Session, device_code: str) -> PlatformCliDeviceAuthorization | None:
    return (
        db.query(PlatformCliDeviceAuthorization)
        .filter(PlatformCliDeviceAuthorization.device_code_hash == _hash_device_code(device_code))
        .first()
    )


def approve_device_authorization(
    db: Session, *, user_code: str, organization_id: str, approved_by_user_id: str, now: datetime | None = None
) -> str:
    """Approve a pending challenge by its user_code. Returns the row status."""
    moment = now or datetime.utcnow()
    row = db.query(PlatformCliDeviceAuthorization).filter_by(user_code=user_code.strip().upper()).first()
    if row is None:
        raise ValueError("unknown_user_code")
    if row.expires_at <= moment:
        row.status = "expired"
        db.commit()
        raise ValueError("expired")
    if row.status not in {"pending", "approved"}:
        raise ValueError("not_pending")
    row.status = "approved"
    row.organization_id = organization_id
    row.approved_by_user_id = approved_by_user_id
    row.approved_at = moment
    db.commit()
    return row.status


def exchange_device_token(db: Session, *, device_code: str, now: datetime | None = None) -> dict:
    """Poll/exchange. Returns a dict with either an OAuth-style pending status or
    a minted short-lived human control-plane token (exactly once)."""
    moment = now or datetime.utcnow()
    row = _lookup(db, device_code)
    if row is None:
        return {"error": "invalid_grant"}
    # Interval enforcement (slow_down) before any state transition.
    too_fast = row.last_polled_at is not None and (moment - row.last_polled_at).total_seconds() < row.interval_seconds
    row.poll_count = (row.poll_count or 0) + 1
    row.last_polled_at = moment
    if row.expires_at <= moment and row.status not in {"consumed"}:
        row.status = "expired"
        db.commit()
        return {"error": "expired_token"}
    if row.status == "consumed":
        db.commit()
        return {"error": "invalid_grant"}  # one-time only; replay rejected
    if row.status == "denied":
        db.commit()
        return {"error": "access_denied"}
    if row.status == "pending":
        db.commit()
        return {"error": "slow_down" if too_fast else "authorization_pending"}
    if row.status == "approved":
        if too_fast:
            db.commit()
            return {"error": "slow_down"}
        token = create_access_token({"sub": row.approved_by_user_id}, expires_delta=HUMAN_TOKEN_TTL)
        row.status = "consumed"
        row.consumed_at = moment
        db.commit()
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": int(HUMAN_TOKEN_TTL.total_seconds()),
            "organization_id": row.organization_id,
        }
    db.commit()
    return {"error": "invalid_grant"}

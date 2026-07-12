"""Signed first-party outreach engagement tokens.

Tracking URLs carry only an opaque outreach send identifier. Recipient details
remain in the server-side send ledger and are never embedded in the URL.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


_TOKEN_CONTEXT = b"agroai-outreach-engagement-v1\x00"


class InvalidTrackingToken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrackingIdentity:
    send_id: str


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def create_tracking_token(*, send_id: str, secret: str) -> str:
    normalized = send_id.strip()
    if not secret:
        raise ValueError("tracking secret is required")
    if not normalized or len(normalized) > 128:
        raise ValueError("valid send_id is required")
    payload = normalized.encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), _TOKEN_CONTEXT + payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def verify_tracking_token(token: str, secret: str) -> TrackingIdentity:
    if not secret:
        raise InvalidTrackingToken("tracking secret is not configured")
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _decode(payload_part)
        provided = _decode(signature_part)
        expected = hmac.new(secret.encode("utf-8"), _TOKEN_CONTEXT + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(provided, expected):
            raise InvalidTrackingToken("invalid signature")
        send_id = payload.decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, InvalidTrackingToken):
            raise
        raise InvalidTrackingToken("malformed tracking token") from exc
    if not send_id or len(send_id) > 128:
        raise InvalidTrackingToken("invalid tracking identity")
    return TrackingIdentity(send_id=send_id)


__all__ = [
    "InvalidTrackingToken",
    "TrackingIdentity",
    "create_tracking_token",
    "verify_tracking_token",
]

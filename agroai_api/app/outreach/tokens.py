"""Signed unsubscribe token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac


class InvalidUnsubscribeToken(ValueError):
    pass


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def create_unsubscribe_token(email: str, secret: str) -> str:
    if not secret:
        raise ValueError("unsubscribe secret is required")
    payload = email.strip().lower().encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def verify_unsubscribe_token(token: str, secret: str) -> str:
    if not secret:
        raise InvalidUnsubscribeToken("unsubscribe secret is not configured")
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _decode(payload_part)
        provided = _decode(signature_part)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(provided, expected):
            raise InvalidUnsubscribeToken("invalid signature")
        email = payload.decode("utf-8").strip().lower()
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, InvalidUnsubscribeToken):
            raise
        raise InvalidUnsubscribeToken("malformed token") from exc
    if email.count("@") != 1:
        raise InvalidUnsubscribeToken("invalid email payload")
    return email


__all__ = ["InvalidUnsubscribeToken", "create_unsubscribe_token", "verify_unsubscribe_token"]

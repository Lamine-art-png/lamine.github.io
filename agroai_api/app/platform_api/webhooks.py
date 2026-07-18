from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import PlatformWebhookAuditEvent, PlatformWebhookEndpoint


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

ALGORITHM = "AES-256-GCM"


@dataclass(frozen=True)
class ResolvedWebhookDestination:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _decode_key(value: str) -> bytes:
    try:
        key = _b64d(value.strip())
    except Exception as exc:
        raise RuntimeError("webhook vault key is not valid base64") from exc
    if len(key) != 32:
        raise RuntimeError("webhook vault key must decode to exactly 32 bytes")
    return key


def webhook_secret_keyring() -> tuple[str, dict[str, bytes]]:
    active = str(getattr(settings, "PLATFORM_API_WEBHOOK_SECRET_ACTIVE_KEY_VERSION", "v1") or "v1").strip()
    raw = str(getattr(settings, "PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON", "") or "").strip()
    if not raw:
        raise RuntimeError("PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON is required")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON must be an object")
    ring = {str(version): _decode_key(str(value)) for version, value in parsed.items()}
    api_key_pepper = str(getattr(settings, "PLATFORM_API_KEY_PEPPER", "") or "").encode("utf-8")
    if api_key_pepper and any(
        len(api_key_pepper) == len(key) and hmac.compare_digest(api_key_pepper, key)
        for key in ring.values()
    ):
        raise RuntimeError("webhook vault keys must not reuse the Platform API key pepper")
    if active not in ring:
        raise RuntimeError("active webhook vault key version is unavailable")
    return active, ring


def _aad(endpoint: PlatformWebhookEndpoint, key_version: str) -> bytes:
    return (
        f"agroai-platform-webhook-v1|{endpoint.organization_id}|"
        f"{endpoint.api_project_id}|{endpoint.id}|{key_version}"
    ).encode("utf-8")


def generate_webhook_secret() -> tuple[str, str, str]:
    plaintext = f"whsec_{secrets.token_urlsafe(32)}"
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, digest, plaintext[:14]


def _encrypt_secret(endpoint: PlatformWebhookEndpoint, plaintext: str) -> tuple[str, str, str]:
    active, ring = webhook_secret_keyring()
    nonce = os.urandom(12)
    ciphertext = AESGCM(ring[active]).encrypt(
        nonce,
        plaintext.encode("utf-8"),
        _aad(endpoint, active),
    )
    return active, _b64e(nonce), _b64e(ciphertext)


def store_webhook_secret(endpoint: PlatformWebhookEndpoint, plaintext: str) -> None:
    version, nonce, ciphertext = _encrypt_secret(endpoint, plaintext)
    endpoint.signing_secret_key_version = version
    endpoint.signing_secret_nonce_b64 = nonce
    endpoint.signing_secret_ciphertext_b64 = ciphertext


def _decrypt(
    endpoint: PlatformWebhookEndpoint,
    *,
    key_version: str | None,
    nonce_b64: str | None,
    ciphertext_b64: str | None,
) -> str:
    if not key_version or not nonce_b64 or not ciphertext_b64:
        raise RuntimeError("webhook signing secret custody is incomplete")
    _active, ring = webhook_secret_keyring()
    key = ring.get(key_version)
    if key is None:
        raise RuntimeError("webhook signing secret key version is unavailable")
    plaintext = AESGCM(key).decrypt(
        _b64d(nonce_b64),
        _b64d(ciphertext_b64),
        _aad(endpoint, key_version),
    )
    return plaintext.decode("utf-8")


def audit_webhook_event(
    db: Session,
    *,
    endpoint: PlatformWebhookEndpoint,
    action: str,
    actor_type: str,
    actor_id: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> PlatformWebhookAuditEvent:
    row = PlatformWebhookAuditEvent(
        organization_id=endpoint.organization_id,
        api_project_id=endpoint.api_project_id,
        endpoint_id=endpoint.id,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
        details_json=dict(details or {}),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    return row


def retrieve_webhook_secret_for_delivery(
    db: Session,
    *,
    endpoint_id: str,
    organization_id: str,
    api_project_id: str,
    worker_id: str,
    request_id: str | None = None,
) -> str:
    endpoint = (
        db.query(PlatformWebhookEndpoint)
        .filter(
            PlatformWebhookEndpoint.id == endpoint_id,
            PlatformWebhookEndpoint.organization_id == organization_id,
            PlatformWebhookEndpoint.api_project_id == api_project_id,
        )
        .first()
    )
    if endpoint is None or endpoint.status != "active" or endpoint.revoked_at is not None:
        raise PermissionError("active webhook endpoint custody denied")
    plaintext = _decrypt(
        endpoint,
        key_version=endpoint.signing_secret_key_version,
        nonce_b64=endpoint.signing_secret_nonce_b64,
        ciphertext_b64=endpoint.signing_secret_ciphertext_b64,
    )
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="secret_retrieved",
        actor_type="delivery_worker",
        actor_id=worker_id,
        request_id=request_id,
    )
    return plaintext


def retrieve_webhook_secrets_for_delivery(
    db: Session,
    *,
    endpoint_id: str,
    organization_id: str,
    api_project_id: str,
    worker_id: str,
    request_id: str | None = None,
) -> list[str]:
    endpoint = (
        db.query(PlatformWebhookEndpoint)
        .filter(
            PlatformWebhookEndpoint.id == endpoint_id,
            PlatformWebhookEndpoint.organization_id == organization_id,
            PlatformWebhookEndpoint.api_project_id == api_project_id,
        )
        .first()
    )
    if endpoint is None or endpoint.status != "active" or endpoint.revoked_at is not None:
        raise PermissionError("active webhook endpoint custody denied")
    secrets_for_attempt = [
        _decrypt(
            endpoint,
            key_version=endpoint.signing_secret_key_version,
            nonce_b64=endpoint.signing_secret_nonce_b64,
            ciphertext_b64=endpoint.signing_secret_ciphertext_b64,
        )
    ]
    if (
        endpoint.previous_secret_expires_at is not None
        and endpoint.previous_secret_expires_at > datetime.utcnow()
        and endpoint.previous_secret_ciphertext_b64
    ):
        secrets_for_attempt.append(
            _decrypt(
                endpoint,
                key_version=endpoint.previous_secret_key_version,
                nonce_b64=endpoint.previous_secret_nonce_b64,
                ciphertext_b64=endpoint.previous_secret_ciphertext_b64,
            )
        )
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="secret_retrieved",
        actor_type="delivery_worker",
        actor_id=worker_id,
        request_id=request_id,
        details={"secret_versions_used": len(secrets_for_attempt)},
    )
    return secrets_for_attempt


def rotate_webhook_secret(
    db: Session,
    *,
    endpoint: PlatformWebhookEndpoint,
    actor_id: str,
    overlap_minutes: int,
) -> str:
    if endpoint.status != "active" or endpoint.revoked_at is not None:
        raise ValueError("only an active webhook endpoint can rotate its secret")
    plaintext, digest, prefix = generate_webhook_secret()
    endpoint.previous_secret_hash = endpoint.signing_secret_hash
    endpoint.previous_secret_key_version = endpoint.signing_secret_key_version
    endpoint.previous_secret_nonce_b64 = endpoint.signing_secret_nonce_b64
    endpoint.previous_secret_ciphertext_b64 = endpoint.signing_secret_ciphertext_b64
    endpoint.previous_secret_expires_at = datetime.utcnow() + timedelta(minutes=max(0, overlap_minutes))
    endpoint.signing_secret_hash = digest
    endpoint.signing_secret_prefix = prefix
    endpoint.signing_secret_version = f"v{int(endpoint.signing_secret_version.removeprefix('v') or '1') + 1}"
    store_webhook_secret(endpoint, plaintext)
    endpoint.updated_at = datetime.utcnow()
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="secret_rotated",
        actor_type="portal_user",
        actor_id=actor_id,
        details={"overlap_minutes": max(0, overlap_minutes)},
    )
    return plaintext


def revoke_webhook_endpoint(db: Session, *, endpoint: PlatformWebhookEndpoint, actor_id: str) -> None:
    endpoint.status = "revoked"
    endpoint.revoked_at = datetime.utcnow()
    endpoint.updated_at = endpoint.revoked_at
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="revoked",
        actor_type="portal_user",
        actor_id=actor_id,
    )


def disable_webhook_endpoint(db: Session, *, endpoint: PlatformWebhookEndpoint, actor_id: str) -> None:
    endpoint.status = "disabled"
    endpoint.disabled_at = datetime.utcnow()
    endpoint.updated_at = endpoint.disabled_at
    audit_webhook_event(
        db,
        endpoint=endpoint,
        action="disabled",
        actor_type="portal_user",
        actor_id=actor_id,
    )


def _allowed_ports() -> set[int]:
    raw = str(getattr(settings, "PLATFORM_API_WEBHOOK_ALLOWED_PORTS", "443") or "443")
    try:
        ports = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise RuntimeError("PLATFORM_API_WEBHOOK_ALLOWED_PORTS is invalid") from exc
    return {port for port in ports if 1 <= port <= 65535}


def _public_address(value: str) -> str:
    address = ipaddress.ip_address(value)
    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise ValueError("webhook URL resolves to a prohibited address")
    return str(address)


def resolve_webhook_destination(
    url: str,
    *,
    resolver: Callable[..., list[Any]] | None = None,
) -> ResolvedWebhookDestination:
    resolver = resolver or socket.getaddrinfo
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("webhook URL must be HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("webhook URL must not include embedded credentials")
    if parsed.query and len(parsed.query) > 4096:
        raise ValueError("webhook URL query is too long")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith((".local", ".internal")):
        raise ValueError("webhook URL host is not allowed")
    port = parsed.port or 443
    if port not in _allowed_ports():
        raise ValueError("webhook URL port is not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = (_public_address(str(literal)),)
    except ValueError as literal_error:
        try:
            answers = resolver(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("webhook URL hostname could not be safely resolved") from exc
        addresses = tuple(sorted({_public_address(str(answer[4][0])) for answer in answers}))
        if not addresses:
            raise ValueError("webhook URL hostname did not resolve")
        if "prohibited address" in str(literal_error):
            raise literal_error
    return ResolvedWebhookDestination(
        url=parsed.geturl(),
        hostname=hostname,
        port=port,
        addresses=addresses,
    )


def validate_webhook_url(url: str) -> str:
    return resolve_webhook_destination(url).url


def webhook_signature(secret: str, *, timestamp: str, event_id: str, payload: bytes) -> str:
    signed = b".".join([timestamp.encode("utf-8"), event_id.encode("utf-8"), payload])
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

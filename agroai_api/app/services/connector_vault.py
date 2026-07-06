from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app.models.connector_security import ConnectorCredential
from app.models.operational_records import ConnectorConnection
from app.services.runtime_key_material import DERIVED_CONNECTOR_KEY_VERSION, derived_connector_vault_key


ALGORITHM = "AES-256-GCM"


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _decode_key(value: str) -> bytes:
    try:
        key = _b64d(value.strip())
    except Exception as exc:
        raise RuntimeError("connector vault key is not valid base64") from exc
    if len(key) != 32:
        raise RuntimeError("connector vault key must decode to exactly 32 bytes")
    return key


def _keyring() -> tuple[str, dict[str, bytes]]:
    active = os.getenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1").strip() or "v1"
    ring: dict[str, bytes] = {}
    raw_ring = os.getenv("CONNECTOR_CREDENTIAL_KEYS_JSON", "").strip()
    if raw_ring:
        try:
            parsed = json.loads(raw_ring)
        except json.JSONDecodeError as exc:
            raise RuntimeError("CONNECTOR_CREDENTIAL_KEYS_JSON is invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("CONNECTOR_CREDENTIAL_KEYS_JSON must be an object")
        ring = {str(version): _decode_key(str(value)) for version, value in parsed.items()}

    single = os.getenv("CONNECTOR_CREDENTIAL_MASTER_KEY", "").strip()
    if single and active not in ring:
        ring[active] = _decode_key(single)

    # The production runtime already requires strong non-default SECRET_KEY and
    # WEBHOOK_SECRET values. When no explicit vault key is supplied, derive a
    # stable, domain-separated AES-256 key from those persistent root secrets.
    # If derivation is available, retain that version in explicit keyrings too so
    # credentials written before a later explicit-key rollout remain readable.
    try:
        derived = derived_connector_vault_key()
    except RuntimeError:
        derived = None
    if derived is not None:
        ring.setdefault(DERIVED_CONNECTOR_KEY_VERSION, derived)
    if not raw_ring and not single:
        if derived is None:
            raise RuntimeError("active connector vault key is not configured")
        active = DERIVED_CONNECTOR_KEY_VERSION

    if active not in ring:
        raise RuntimeError("active connector vault key is not configured")
    return active, ring


def vault_configured() -> bool:
    try:
        _keyring()
        return True
    except RuntimeError:
        return False


def _aad(tenant_id: str, connection_id: str, provider: str, key_version: str) -> bytes:
    return f"agroai-connector-v1|{tenant_id}|{connection_id}|{provider}|{key_version}".encode("utf-8")


def credential_reference(row: ConnectorCredential) -> str:
    return f"vault://connector-credentials/{row.id}"


def store_connector_credentials(
    db: Session,
    *,
    tenant_id: str,
    connection: ConnectorConnection,
    provider: str,
    payload: dict[str, Any],
    token_expires_at: datetime | None = None,
    scopes: list[str] | None = None,
) -> ConnectorCredential:
    if connection.tenant_id != tenant_id or connection.provider != provider:
        raise ValueError("connector credential ownership mismatch")
    active_version, ring = _keyring()
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(ring[active_version]).encrypt(
        nonce,
        plaintext,
        _aad(tenant_id, connection.id, provider, active_version),
    )
    row = db.query(ConnectorCredential).filter(ConnectorCredential.connection_id == connection.id).first()
    now = datetime.utcnow()
    if row is None:
        row = ConnectorCredential(
            tenant_id=tenant_id,
            connection_id=connection.id,
            provider=provider,
            created_at=now,
        )
        db.add(row)
    row.key_version = active_version
    row.algorithm = ALGORITHM
    row.nonce_b64 = _b64e(nonce)
    row.ciphertext_b64 = _b64e(ciphertext)
    row.token_expires_at = token_expires_at
    row.scopes_json = list(scopes or [])
    row.revoked_at = None
    row.updated_at = now
    db.flush()
    return row


def load_connector_credentials(
    db: Session,
    *,
    tenant_id: str,
    connection_id: str,
) -> dict[str, Any]:
    row = db.query(ConnectorCredential).filter(
        ConnectorCredential.connection_id == connection_id,
        ConnectorCredential.tenant_id == tenant_id,
        ConnectorCredential.revoked_at.is_(None),
    ).first()
    if row is None:
        raise LookupError("active connector credentials not found")
    if row.algorithm != ALGORITHM:
        raise RuntimeError("unsupported connector credential algorithm")
    _active, ring = _keyring()
    key = ring.get(row.key_version)
    if key is None:
        raise RuntimeError("connector credential key version is unavailable")
    plaintext = AESGCM(key).decrypt(
        _b64d(row.nonce_b64),
        _b64d(row.ciphertext_b64),
        _aad(row.tenant_id, row.connection_id, row.provider, row.key_version),
    )
    value = json.loads(plaintext.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("connector credential payload is invalid")
    return value


def revoke_connector_credentials(db: Session, *, tenant_id: str, connection_id: str) -> bool:
    row = db.query(ConnectorCredential).filter(
        ConnectorCredential.connection_id == connection_id,
        ConnectorCredential.tenant_id == tenant_id,
        ConnectorCredential.revoked_at.is_(None),
    ).first()
    if row is None:
        return False
    row.revoked_at = datetime.utcnow()
    db.flush()
    return True

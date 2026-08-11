from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.services.runtime_key_material import derive_runtime_key

ALGORITHM = "AES-256-GCM"
KEY_VERSION = "derived-identity-v1"
SECRET_KEY_FALLBACK_VERSION = "derived-identity-secret-key-v1"
WEBHOOK_SECRET_FALLBACK_VERSION = "derived-identity-webhook-secret-v1"


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _single_secret_key(secret: str, *, label: bytes) -> bytes:
    return hmac.new(label, secret.encode("utf-8"), hashlib.sha256).digest()


def _key_material() -> tuple[str, bytes]:
    """Return stable identity-vault material without making registration depend
    on an unrelated second secret.

    Existing installations with both runtime roots keep the original key and
    version. A production environment that has only the application signing
    secret (or only the webhook root) receives a separately versioned,
    domain-separated fallback so account creation does not fail with HTTP 500.
    """

    try:
        key = derive_runtime_key("identity-verification-vault")
    except RuntimeError:
        secret_key = str(getattr(settings, "SECRET_KEY", "") or "").strip()
        if secret_key:
            return SECRET_KEY_FALLBACK_VERSION, _single_secret_key(
                secret_key,
                label=b"agroai-identity-secret-key-root-v1",
            )
        webhook_secret = str(getattr(settings, "WEBHOOK_SECRET", "") or "").strip()
        if webhook_secret:
            return WEBHOOK_SECRET_FALLBACK_VERSION, _single_secret_key(
                webhook_secret,
                label=b"agroai-identity-webhook-secret-root-v1",
            )
        raise RuntimeError("identity vault key material is not configured")
    if len(key) != 32:
        raise RuntimeError("identity vault key must be exactly 32 bytes")
    return KEY_VERSION, key


def _key_for_version(key_version: str) -> bytes:
    if key_version == KEY_VERSION:
        key = derive_runtime_key("identity-verification-vault")
    elif key_version == SECRET_KEY_FALLBACK_VERSION:
        secret_key = str(getattr(settings, "SECRET_KEY", "") or "").strip()
        if not secret_key:
            raise RuntimeError("identity vault SECRET_KEY fallback is unavailable")
        key = _single_secret_key(secret_key, label=b"agroai-identity-secret-key-root-v1")
    elif key_version == WEBHOOK_SECRET_FALLBACK_VERSION:
        webhook_secret = str(getattr(settings, "WEBHOOK_SECRET", "") or "").strip()
        if not webhook_secret:
            raise RuntimeError("identity vault WEBHOOK_SECRET fallback is unavailable")
        key = _single_secret_key(webhook_secret, label=b"agroai-identity-webhook-secret-root-v1")
    else:
        raise RuntimeError("unsupported identity vault key version")
    if len(key) != 32:
        raise RuntimeError("identity vault key must be exactly 32 bytes")
    return key


def _aad(organization_id: str, profile_id: str, key_version: str) -> bytes:
    return f"agroai-identity-v1|{organization_id}|{profile_id}|{key_version}".encode("utf-8")


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    prefix = "+" if raw.startswith("+") else ""
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone number must contain 8 to 15 digits")
    return f"{prefix}{digits}"


def encrypt_phone(value: str, *, organization_id: str, profile_id: str) -> dict[str, str]:
    normalized = normalize_phone(value)
    key_version, key = _key_material()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        normalized.encode("utf-8"),
        _aad(organization_id, profile_id, key_version),
    )
    return {
        "algorithm": ALGORITHM,
        "key_version": key_version,
        "nonce_b64": _b64e(nonce),
        "ciphertext_b64": _b64e(ciphertext),
        "last4": normalized[-4:],
    }


def decrypt_phone(
    *,
    ciphertext_b64: str,
    nonce_b64: str,
    organization_id: str,
    profile_id: str,
    key_version: str = KEY_VERSION,
) -> str:
    plaintext = AESGCM(_key_for_version(key_version)).decrypt(
        _b64d(nonce_b64),
        _b64d(ciphertext_b64),
        _aad(organization_id, profile_id, key_version),
    )
    return plaintext.decode("utf-8")

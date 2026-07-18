from __future__ import annotations

import base64
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.runtime_key_material import derive_runtime_key

ALGORITHM = "AES-256-GCM"
KEY_VERSION = "derived-identity-v1"


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _key() -> bytes:
    key = derive_runtime_key("identity-verification-vault")
    if len(key) != 32:
        raise RuntimeError("identity vault key must be exactly 32 bytes")
    return key


def _aad(organization_id: str, profile_id: str) -> bytes:
    return f"agroai-identity-v1|{organization_id}|{profile_id}|{KEY_VERSION}".encode("utf-8")


def normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    prefix = "+" if raw.startswith("+") else ""
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone number must contain 8 to 15 digits")
    return f"{prefix}{digits}"


def encrypt_phone(value: str, *, organization_id: str, profile_id: str) -> dict[str, str]:
    normalized = normalize_phone(value)
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(
        nonce,
        normalized.encode("utf-8"),
        _aad(organization_id, profile_id),
    )
    return {
        "algorithm": ALGORITHM,
        "key_version": KEY_VERSION,
        "nonce_b64": _b64e(nonce),
        "ciphertext_b64": _b64e(ciphertext),
        "last4": normalized[-4:],
    }


def decrypt_phone(*, ciphertext_b64: str, nonce_b64: str, organization_id: str, profile_id: str) -> str:
    plaintext = AESGCM(_key()).decrypt(
        _b64d(nonce_b64),
        _b64d(ciphertext_b64),
        _aad(organization_id, profile_id),
    )
    return plaintext.decode("utf-8")

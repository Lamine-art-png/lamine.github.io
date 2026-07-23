"""Small, domain-separated cryptographic helpers for WhatsApp identifiers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.runtime_key_material import derived_connector_vault_key

_KEY_VERSION = "derived-v1"
_DIGITS = re.compile(r"\D+")


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_wa_id(value: str) -> str:
    normalized = _DIGITS.sub("", str(value or ""))
    if not 7 <= len(normalized) <= 32:
        raise ValueError("WhatsApp identifier must contain 7 to 32 digits")
    return normalized


def masked_wa_id(value: str) -> str:
    normalized = normalize_wa_id(value)
    return f"••••{normalized[-4:]}"


def _subkey(purpose: bytes) -> bytes:
    root = derived_connector_vault_key()
    return hmac.new(root, b"agroai-whatsapp|" + purpose, hashlib.sha256).digest()


def wa_id_hash(value: str) -> str:
    normalized = normalize_wa_id(value)
    return hmac.new(_subkey(b"lookup-v1"), normalized.encode("ascii"), hashlib.sha256).hexdigest()


def encrypt_wa_id(value: str, *, tenant_id: str, binding_id: str) -> tuple[str, str, str]:
    normalized = normalize_wa_id(value)
    nonce = __import__("os").urandom(12)
    aad = f"agroai-whatsapp-id-v1|{tenant_id}|{binding_id}|{_KEY_VERSION}".encode("utf-8")
    ciphertext = AESGCM(_subkey(b"encryption-v1")).encrypt(nonce, normalized.encode("ascii"), aad)
    return _b64e(ciphertext), _b64e(nonce), _KEY_VERSION


def decrypt_wa_id(
    ciphertext_b64: str,
    nonce_b64: str,
    *,
    tenant_id: str,
    binding_id: str,
    key_version: str,
) -> str:
    if key_version != _KEY_VERSION:
        raise RuntimeError("unsupported WhatsApp identifier key version")
    aad = f"agroai-whatsapp-id-v1|{tenant_id}|{binding_id}|{key_version}".encode("utf-8")
    plaintext = AESGCM(_subkey(b"encryption-v1")).decrypt(_b64d(nonce_b64), _b64d(ciphertext_b64), aad)
    return normalize_wa_id(plaintext.decode("ascii"))


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left or "").encode("utf-8"), str(right or "").encode("utf-8"))

from __future__ import annotations

import hashlib
import hmac

from app.core.config import settings


DERIVED_CONNECTOR_KEY_VERSION = "derived-v1"


def _root_material() -> bytes:
    secret_key = (settings.SECRET_KEY or "").strip()
    webhook_secret = (settings.WEBHOOK_SECRET or "").strip()
    if not secret_key or not webhook_secret:
        raise RuntimeError("runtime root key material is not configured")
    material = f"{secret_key}\x00{webhook_secret}".encode("utf-8")
    return hmac.new(b"agroai-runtime-root-v1", material, hashlib.sha256).digest()


def derive_runtime_key(purpose: str) -> bytes:
    label = (purpose or "").strip()
    if not label:
        raise ValueError("runtime key purpose is required")
    root = _root_material()
    return hmac.new(root, f"agroai:{label}:v1".encode("utf-8"), hashlib.sha256).digest()


def derived_connector_vault_key() -> bytes:
    return derive_runtime_key("connector-credential-vault")


def derived_oauth_state_signing_key() -> bytes:
    return derive_runtime_key("oauth-state-signing")

"""Recursive credential guard for paid AGRO-AI Intelligence input.

Customer agricultural context can be arbitrarily nested JSON. Reject likely
credentials anywhere in that structure before the request reaches an external
inference provider. The public request contract remains agricultural context,
not a secret transport.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from app.api.v1 import commercial_intelligence as legacy


_original_execute_paid_intelligence = legacy._execute_paid_intelligence

_SENSITIVE_EXACT = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "stripe_secret_key",
    "bearer_token",
}
_SENSITIVE_SUFFIXES = (
    "_password",
    "_passwd",
    "_secret",
    "_token",
    "_api_key",
    "_private_key",
    "_client_secret",
)
_MAX_SCAN_DEPTH = 16


def _normalized_key(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return text[:160]


def _credential_path(value: Any, *, path: str = "input", depth: int = 0) -> str | None:
    if depth > _MAX_SCAN_DEPTH:
        # Deeply recursive data is not needed for the commercial agricultural
        # input contract and can hide secrets from reliable inspection.
        return path
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            child_path = f"{path}.{key}"
            if normalized in _SENSITIVE_EXACT or any(normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
                return child_path
            found = _credential_path(child, path=child_path, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _credential_path(child, path=f"{path}[{index}]", depth=depth + 1)
            if found:
                return found
    return None


async def _guarded_execute_paid_intelligence(*, payload: Any, **kwargs: Any) -> dict[str, Any]:
    credential_path = _credential_path(getattr(payload, "input", {}))
    if credential_path:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "credential_like_input_rejected",
                "message": "Remove credentials, API keys, tokens, passwords, and private secrets from agricultural intelligence input.",
                "field": credential_path[:240],
            },
        )
    return await _original_execute_paid_intelligence(payload=payload, **kwargs)


legacy._execute_paid_intelligence = _guarded_execute_paid_intelligence

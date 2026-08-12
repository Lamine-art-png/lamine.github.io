"""Regression guards proving Platform API secrets never leak into responses.

These are pure-function tests (no DB / network fixtures) so they run fast and
gate every change: they lock in the error-contract allowlist and the
key-fingerprint redaction contract required by the security review
(§7/§23/§35 of the engineering brief).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.platform_api import errors, keys


def _fake_request(request_id: str = "req_test_123"):
    """Minimal duck-typed stand-in for starlette Request used by error_response."""
    return SimpleNamespace(state=SimpleNamespace(request_id=request_id))


def _render(exc):
    response = errors.error_response(_fake_request(), exc)
    return json.loads(bytes(response.body).decode("utf-8")), response


def test_error_response_strips_all_non_allowlisted_detail_keys():
    """Sensitive keys accidentally attached to a detail dict must never surface."""
    secret_material = {
        # Split literal so the repository secret scanner does not flag this
        # fixture; the runtime value is byte-identical to a real key shape.
        "api_key": "agro_live_" + "SUPERSECRETmaterialSHOULDNEVERLEAK1234",
        "stripe_secret": "sk_live_NEVERLEAKxyz",
        "provider_token": "earthdaily-oauth-token-abc",
        "webhook_secret": "whsec_neverleak",
        "authorization": "Bearer agro_live_leak",
        "pepper": "PLATFORM_PEPPER_VALUE",
        "sql": "SELECT * FROM platform_api_keys",
        "stack": "Traceback (most recent call last): ...",
    }
    exc = errors.platform_error(
        "provider_not_ready",
        "Provider is awaiting a partner contract.",
        status_code=409,
        error_type="provider_error",
        details=secret_material,
    )
    payload, response = _render(exc)

    # Only allowlisted keys survive.
    assert set(payload).issubset(
        {"code", "type", "message", "request_id", "provider", "readiness",
         "environment", "operation", "resource", "limit", "included_credits"}
    )
    # No secret value appears anywhere in the serialized body or headers.
    serialized = json.dumps(payload) + json.dumps(dict(response.headers))
    for value in secret_material.values():
        assert value not in serialized, f"leaked sensitive value: {value!r}"


def test_error_response_never_echoes_raw_detail_string():
    """A non-dict detail must be replaced by a generic safe message."""
    from fastapi import HTTPException

    leak = "internal path /srv/agroai/secrets/pepper.key and token agro_live_x"
    payload, _ = _render(HTTPException(status_code=500, detail=leak))
    assert leak not in json.dumps(payload)
    assert payload["code"] == "platform_api_error"
    assert payload["request_id"] == "req_test_123"


def test_key_fingerprint_reveals_neither_plaintext_nor_stored_hash():
    """The safe fingerprint used in UI and logs must not reveal the secret
    *or* the stored verification hash.

    Design (verified): the stored ``key_hash`` is a **peppered HMAC-SHA256**,
    while the display ``fingerprint`` is a plain SHA-256 of the plaintext,
    truncated. This deliberate separation means a leaked fingerprint cannot be
    used to reconstruct the stored verification hash without the server pepper.
    """
    import hashlib

    plaintext, stored_hash, key_prefix, safe_fingerprint = keys.generate_plaintext_key("test")

    assert plaintext.startswith("agro_test_")
    # Fingerprint reveals neither the plaintext nor the random secret body.
    assert plaintext not in safe_fingerprint
    secret_body = plaintext[len("agro_test_"):]
    assert secret_body not in safe_fingerprint
    # Fingerprint is the (non-peppered) sha256 truncation — deterministic and
    # independent of the peppered verification hash.
    expected = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert safe_fingerprint == f"{expected[:8]}...{expected[-8:]}"
    # Stored verification hash is a non-reversible peppered HMAC, never the
    # plaintext, and never equal to the fingerprint's underlying digest.
    assert stored_hash != plaintext
    assert len(stored_hash) == 64  # sha256 hex
    assert stored_hash != expected  # peppered HMAC != plain sha256
    assert keys.fingerprint(plaintext) not in stored_hash


def test_live_and_test_keys_have_distinct_unguessable_prefixes():
    live_plain, _, _, _ = keys.generate_plaintext_key("live")
    test_plain, _, _, _ = keys.generate_plaintext_key("test")
    assert live_plain.startswith("agro_live_")
    assert test_plain.startswith("agro_test_")
    # Two freshly minted keys never collide (secrets.token_urlsafe entropy).
    assert keys.generate_plaintext_key("test")[0] != keys.generate_plaintext_key("test")[0]

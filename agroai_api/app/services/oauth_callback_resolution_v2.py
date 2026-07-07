"""Deterministic redirect resolution for one-time OAuth callback state."""
from __future__ import annotations

import hmac
from typing import Any

from sqlalchemy.orm import Session

from app.services.oauth_state_store import _decode, _digest, consume_oauth_state


def consume_state_for_signed_provider_redirect(
    db: Session,
    *,
    state: str,
    redirect_url: str,
) -> dict[str, Any] | None:
    """Verify the exact provider callback against the redirect hash in signed state."""
    payload = _decode(state)
    if payload is None:
        return None
    expected_hash = payload.get("redirect_sha256")
    candidate = str(redirect_url or "").strip()
    if not isinstance(expected_hash, str) or not expected_hash or not candidate:
        return None
    if not hmac.compare_digest(_digest(candidate), expected_hash):
        return None
    return consume_oauth_state(db, state=state, redirect_url=candidate)


def install_exact_oauth_callback_resolution() -> None:
    """Resolve callback URL from the provider identity already signed into state."""
    from app.api.v1 import connector_launch

    def exact_callback_consumer(db: Session, state: str) -> dict[str, Any] | None:
        payload = _decode(state)
        if payload is None:
            return None
        provider = str(payload.get("provider") or "").strip()
        if provider not in connector_launch.OAUTH_PROVIDERS:
            return None
        return consume_state_for_signed_provider_redirect(
            db,
            state=state,
            redirect_url=connector_launch.callback_url_for(provider),
        )

    connector_launch._consume_state_for_known_callback = exact_callback_consumer

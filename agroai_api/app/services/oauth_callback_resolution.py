"""Deterministic redirect resolution for one-time OAuth callback state."""
from __future__ import annotations

import hmac
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.services.oauth_state_store import _decode, _hash_text, consume_oauth_state


def consume_state_for_exact_known_redirect(
    db: Session,
    *,
    state: str,
    candidate_redirects: Iterable[str],
) -> dict[str, Any] | None:
    """Consume state only against the configured URL matching its signed hash.

    The existing OAuth state already contains a signed ``redirect_hash``. Resolve
    that hash first instead of iterating DB consumption attempts across an
    unordered set of URLs. The original single-use nonce, signature, expiry,
    tenant, provider, connection, and redirect checks remain authoritative inside
    ``consume_oauth_state``.
    """
    payload = _decode(state)
    if payload is None:
        return None
    expected_hash = payload.get("redirect_hash")
    if not isinstance(expected_hash, str) or not expected_hash:
        return None

    matches = []
    for candidate in dict.fromkeys(str(item) for item in candidate_redirects if item):
        if hmac.compare_digest(_hash_text(candidate), expected_hash):
            matches.append(candidate)

    if len(matches) != 1:
        return None
    return consume_oauth_state(db, state=state, redirect_url=matches[0])


def install_exact_oauth_callback_resolution() -> None:
    """Patch the loaded callback module without changing its route identity."""
    from app.api.v1 import connector_launch

    def exact_callback_consumer(db: Session, state: str) -> dict[str, Any] | None:
        candidates = {connector_launch.API_OAUTH_CALLBACK_URL}
        for provider in connector_launch.PROVIDER_ENV:
            candidates.add(connector_launch.callback_url_for(provider))
        return consume_state_for_exact_known_redirect(
            db,
            state=state,
            candidate_redirects=candidates,
        )

    connector_launch._consume_state_for_known_callback = exact_callback_consumer

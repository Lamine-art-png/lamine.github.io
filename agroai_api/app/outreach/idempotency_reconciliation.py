"""Safe reconciliation for provider-accepted idempotent outreach requests."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.base import engine


def provider_error_type(response_body: str | None) -> str | None:
    """Return Resend's stable error type without exposing provider payloads."""
    if not response_body:
        return None
    try:
        payload = json.loads(response_body)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("name", "type", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("name") or value.get("type")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def reconcile_provider_accepted_send(
    *,
    idempotency_key: str,
    metadata: dict[str, Any],
) -> str | None:
    """Promote the original failed tracking record after Resend confirms key reuse.

    Resend's ``invalid_idempotent_request`` means the key was already used with a
    different payload. Because each retry receives a new tracking send id, the
    original provider-accepted payload belongs to the earliest failed live record
    for this idempotency key. Promoting that record preserves the tracking links
    already embedded in the delivered email and avoids a duplicate send.
    """
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id, metadata_json FROM outreach_sends "
                "WHERE idempotency_key=:idempotency_key AND dry_run=0 AND status='failed' "
                "ORDER BY created_at ASC LIMIT 1"
            ),
            {"idempotency_key": idempotency_key},
        ).mappings().first()
        if row is None:
            return None
        existing: dict[str, Any] = {}
        try:
            parsed = json.loads(str(row.get("metadata_json") or "{}"))
            if isinstance(parsed, dict):
                existing = parsed
        except (TypeError, json.JSONDecodeError):
            pass
        merged = {
            **existing,
            **metadata,
            "provider_reconciled": True,
            "provider_reconciliation_reason": "invalid_idempotent_request_confirms_prior_provider_acceptance",
        }
        send_id = str(row["id"])
        conn.execute(
            text(
                "UPDATE outreach_sends SET status='sent', error_text=NULL, metadata_json=:metadata_json "
                "WHERE id=:send_id AND status='failed'"
            ),
            {"send_id": send_id, "metadata_json": json.dumps(merged, ensure_ascii=False)},
        )
    return send_id


__all__ = ["provider_error_type", "reconcile_provider_accepted_send"]

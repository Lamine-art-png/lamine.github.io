"""Bounded, customer-safe Platform API abuse signals."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.platform_product import PlatformAbuseEvent


def record_abuse_signal(
    db: Session,
    *,
    signal_type: str,
    severity: str,
    organization_id: str | None = None,
    api_project_id: str | None = None,
    api_key_id: str | None = None,
    automated_action: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> PlatformAbuseEvent:
    row = PlatformAbuseEvent(
        organization_id=organization_id,
        api_project_id=api_project_id,
        api_key_id=api_key_id,
        signal_type=signal_type[:120],
        severity=severity[:40],
        status="open",
        automated_action=automated_action[:80] if automated_action else None,
        evidence_summary_json={
            str(key)[:80]: (
                value
                if isinstance(value, (bool, int, float)) or value is None
                else str(value)[:240]
            )
            for key, value in (evidence or {}).items()
        },
    )
    db.add(row)
    return row

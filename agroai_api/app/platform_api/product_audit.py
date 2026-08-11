from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.metrics import platform_product_events
from app.models.platform_product import PlatformProductAuditEvent


def record_product_audit(
    db: Session,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    outcome: str = "success",
    organization_id: str | None = None,
    actor_user_id: str | None = None,
    actor_type: str = "portal_user",
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> PlatformProductAuditEvent:
    parts = event_type.split(".")
    subsystem = parts[1] if len(parts) > 1 else "platform"
    action = ".".join(parts[2:]) if len(parts) > 2 else event_type
    platform_product_events.labels(
        subsystem=subsystem[:80],
        action=action[:120],
        outcome=outcome[:40],
    ).inc()
    row = PlatformProductAuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        outcome=outcome,
        reason=reason,
        metadata_json=metadata or {},
        request_id=request_id,
    )
    db.add(row)
    return row

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.platform_api import PlatformApiUsageEvent
from app.platform_api.principal import PlatformPrincipal


def record_usage_event(
    db: Session,
    *,
    principal: PlatformPrincipal,
    event_type: str,
    metric: str,
    operation: str,
    route: str | None = None,
    method: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    quantity: int = 1,
    cost_units: int = 1,
    status_code: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlatformApiUsageEvent | None:
    if not principal.organization_id or not principal.api_project_id:
        return None
    row = PlatformApiUsageEvent(
        id=str(uuid.uuid4()),
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        service_account_id=principal.service_account_id,
        api_key_id=principal.api_key_id,
        workspace_id=principal.workspace_id,
        environment=principal.environment or "test",
        event_type=event_type,
        metric=metric,
        quantity=max(1, int(quantity)),
        cost_units=max(1, int(cost_units)),
        operation=operation,
        route=route,
        method=method,
        request_id=request_id or principal.request_id,
        idempotency_key=idempotency_key or f"usage:{uuid.uuid4()}",
        status_code=status_code,
        metadata_json=dict(metadata or {}),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    return row

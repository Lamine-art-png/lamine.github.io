from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import PlatformIdempotencyRecord
from app.platform_api.principal import PlatformPrincipal


def request_hash(payload: Any) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def begin_idempotent_operation(
    db: Session,
    *,
    principal: PlatformPrincipal,
    operation: str,
    idempotency_key: str | None,
    payload: Any,
) -> tuple[PlatformIdempotencyRecord | None, bool]:
    if not idempotency_key:
        return None, False
    if not principal.organization_id or not principal.api_project_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Platform API principal required")
    digest = request_hash(payload)
    row = (
        db.query(PlatformIdempotencyRecord)
        .filter(
            PlatformIdempotencyRecord.organization_id == principal.organization_id,
            PlatformIdempotencyRecord.api_project_id == principal.api_project_id,
            PlatformIdempotencyRecord.operation == operation,
            PlatformIdempotencyRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if row is not None:
        if row.request_hash != digest:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "idempotency_conflict",
                    "type": "idempotency_error",
                    "message": "The idempotency key was already used with a different request payload.",
                    "request_id": principal.request_id,
                },
            )
        return row, row.status == "completed"

    now = datetime.utcnow()
    row = PlatformIdempotencyRecord(
        id=str(uuid.uuid4()),
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=digest,
        status="in_progress",
        operation_id=str(uuid.uuid4()),
        first_request_id=principal.request_id,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=max(1, int(getattr(settings, "PLATFORM_API_IDEMPOTENCY_TTL_HOURS", 24) or 24))),
    )
    db.add(row)
    db.flush()
    return row, False


def complete_idempotent_operation(
    row: PlatformIdempotencyRecord | None,
    *,
    response_status: int,
    response_json: dict[str, Any],
) -> None:
    if row is None:
        return
    row.status = "completed"
    row.response_status = response_status
    row.response_json = response_json
    row.updated_at = datetime.utcnow()

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import insert, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import PlatformIdempotencyRecord
from app.platform_api.principal import PlatformPrincipal


def request_hash(payload: Any, *, scope: str = "") -> str:
    encoded = json.dumps(
        {"scope": scope, "payload": payload or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _error(principal: PlatformPrincipal, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "type": "idempotency_error",
            "message": message,
            "request_id": principal.request_id,
        },
    )


def _scope_filter(principal: PlatformPrincipal, operation: str, idempotency_key: str):
    return (
        PlatformIdempotencyRecord.organization_id == principal.organization_id,
        PlatformIdempotencyRecord.api_project_id == principal.api_project_id,
        PlatformIdempotencyRecord.operation == operation,
        PlatformIdempotencyRecord.idempotency_key == idempotency_key,
    )


def _claim_insert(db: Session, values: dict[str, Any]) -> bool:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(PlatformIdempotencyRecord).values(**values).on_conflict_do_nothing(
            constraint="uq_platform_idempotency_scope"
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(PlatformIdempotencyRecord).values(**values).on_conflict_do_nothing(
            index_elements=["organization_id", "api_project_id", "operation", "idempotency_key"]
        )
    else:
        statement = insert(PlatformIdempotencyRecord).values(**values)
    if dialect in {"postgresql", "sqlite"}:
        result = db.execute(statement.returning(PlatformIdempotencyRecord.id))
        return result.scalar_one_or_none() is not None
    result = db.execute(statement)
    return result.rowcount == 1


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

    now = datetime.utcnow()
    ttl = timedelta(hours=max(1, int(getattr(settings, "PLATFORM_API_IDEMPOTENCY_TTL_HOURS", 24) or 24)))
    scope = f"{principal.organization_id}|{principal.api_project_id}|{operation}"
    digest = request_hash(payload, scope=scope)
    record_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    values = {
        "id": record_id,
        "organization_id": principal.organization_id,
        "api_project_id": principal.api_project_id,
        "operation": operation,
        "idempotency_key": idempotency_key,
        "request_hash": digest,
        "status": "in_progress",
        "operation_id": operation_id,
        "first_request_id": principal.request_id,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + ttl,
    }
    if _claim_insert(db, values):
        return db.get(PlatformIdempotencyRecord, record_id), False

    filters = _scope_filter(principal, operation, idempotency_key)
    reclaimed = db.execute(
        update(PlatformIdempotencyRecord)
        .where(*filters, PlatformIdempotencyRecord.expires_at <= now)
        .values(
            request_hash=digest,
            status="in_progress",
            response_status=None,
            response_json=None,
            operation_id=operation_id,
            first_request_id=principal.request_id,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
        )
    )
    if reclaimed.rowcount == 1:
        row = db.query(PlatformIdempotencyRecord).filter(*filters).one()
        return row, False

    row = db.query(PlatformIdempotencyRecord).filter(*filters).one()
    if row.request_hash != digest:
        raise _error(
            principal,
            "idempotency_conflict",
            "The idempotency key was already used with a different request payload.",
        )
    if row.status == "completed":
        return row, True
    raise _error(
        principal,
        "operation_in_progress",
        "An identical operation with this idempotency key is still in progress.",
    )


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

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
from app.models.platform_product import PlatformCheckoutIdempotency


CHECKOUT_OPERATION = "stripe_checkout.create"


def canonical_checkout_hash(
    *,
    organization_id: str,
    operation: str,
    payload: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "organization_id": organization_id,
            "operation": operation,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stripe_checkout_idempotency_key(
    *,
    organization_id: str,
    operation: str,
    client_key: str,
    request_hash: str,
) -> str:
    digest = hashlib.sha256(
        f"{organization_id}\0{operation}\0{client_key}\0{request_hash}".encode("utf-8")
    ).hexdigest()
    return f"agroai-platform-checkout-{digest}"


def _claim_insert(db: Session, values: dict[str, Any]) -> bool:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(PlatformCheckoutIdempotency)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_platform_checkout_idempotency_scope")
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(PlatformCheckoutIdempotency)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["organization_id", "operation", "client_key"]
            )
        )
    else:
        statement = insert(PlatformCheckoutIdempotency).values(**values)
    if dialect in {"postgresql", "sqlite"}:
        result = db.execute(statement.returning(PlatformCheckoutIdempotency.id))
        return result.scalar_one_or_none() is not None
    return db.execute(statement).rowcount == 1


def _conflict(code: str, message: str, request_id: str | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "type": "idempotency_error",
            "message": message,
            "request_id": request_id,
        },
    )


def claim_checkout(
    db: Session,
    *,
    organization_id: str,
    client_key: str,
    payload: dict[str, Any],
    request_id: str | None,
    operation: str = CHECKOUT_OPERATION,
) -> tuple[PlatformCheckoutIdempotency, bool]:
    now = datetime.utcnow()
    ttl = timedelta(
        hours=max(
            1,
            int(getattr(settings, "PLATFORM_API_IDEMPOTENCY_TTL_HOURS", 24) or 24),
        )
    )
    digest = canonical_checkout_hash(
        organization_id=organization_id,
        operation=operation,
        payload=payload,
    )
    record_id = str(uuid.uuid4())
    values = {
        "id": record_id,
        "organization_id": organization_id,
        "operation": operation,
        "client_key": client_key,
        "request_hash": digest,
        "status": "in_progress",
        "first_request_id": request_id,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + ttl,
    }
    if _claim_insert(db, values):
        return db.get(PlatformCheckoutIdempotency, record_id), False

    filters = (
        PlatformCheckoutIdempotency.organization_id == organization_id,
        PlatformCheckoutIdempotency.operation == operation,
        PlatformCheckoutIdempotency.client_key == client_key,
    )
    row = db.query(PlatformCheckoutIdempotency).filter(*filters).one()
    if row.request_hash != digest:
        raise _conflict(
            "idempotency_conflict",
            "The Checkout idempotency key was already used with a different payload.",
            request_id,
        )
    if row.status == "completed" and isinstance(row.response_json, dict):
        return row, True
    if row.status == "in_progress" and row.expires_at > now:
        raise _conflict(
            "operation_in_progress",
            "An identical Checkout operation is still in progress.",
            request_id,
        )
    reclaimed = db.execute(
        update(PlatformCheckoutIdempotency)
        .where(
            *filters,
            PlatformCheckoutIdempotency.request_hash == digest,
            (
                (PlatformCheckoutIdempotency.expires_at <= now)
                | (PlatformCheckoutIdempotency.status == "failed")
            ),
        )
        .values(
            status="in_progress",
            subscription_id=None,
            stripe_checkout_session_id=None,
            response_json=None,
            first_request_id=request_id,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
        )
    )
    if reclaimed.rowcount == 1:
        return db.query(PlatformCheckoutIdempotency).filter(*filters).one(), False
    raise _conflict(
        "operation_in_progress",
        "An identical Checkout operation is still in progress.",
        request_id,
    )


def complete_checkout(
    row: PlatformCheckoutIdempotency,
    *,
    subscription_id: str,
    stripe_checkout_session_id: str | None,
    response_json: dict[str, Any],
) -> None:
    row.status = "completed"
    row.subscription_id = subscription_id
    row.stripe_checkout_session_id = stripe_checkout_session_id
    row.response_json = response_json
    row.updated_at = datetime.utcnow()


def fail_checkout(row: PlatformCheckoutIdempotency) -> None:
    row.status = "failed"
    row.updated_at = datetime.utcnow()

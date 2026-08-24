"""Small PostgreSQL transaction-lock helper for intelligence memory.

Unique constraints remain the final integrity boundary. Advisory transaction
locks serialize first-write races for logical keys that do not yet have a row
available for SELECT ... FOR UPDATE.
"""
from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlalchemy.orm import Session


def _signed_lock_key(namespace: str, key: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def advisory_xact_lock(db: Session, namespace: str, key: str) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    db.execute(
        sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _signed_lock_key(namespace, key)},
    )

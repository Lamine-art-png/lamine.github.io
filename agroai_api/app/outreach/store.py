"""Durable outreach suppression and send ledger on the existing AGRO-AI database.

Schema ownership belongs exclusively to Alembic. Runtime code only reads and
writes the tables introduced by revision 017_outreach_machine.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db.base import engine


class OutreachStore:
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def is_suppressed(self, email: str) -> bool:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT email FROM outreach_suppression WHERE email=:email"),
                {"email": email.strip().lower()},
            ).first()
        return row is not None

    def suppress(self, email: str, reason: str) -> None:
        normalized = email.strip().lower()
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT email FROM outreach_suppression WHERE email=:email"),
                {"email": normalized},
            ).first()
            if existing:
                conn.execute(
                    text(
                        "UPDATE outreach_suppression "
                        "SET reason=:reason, created_at=:created_at "
                        "WHERE email=:email"
                    ),
                    {
                        "email": normalized,
                        "reason": reason[:240],
                        "created_at": self._now(),
                    },
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO outreach_suppression "
                        "(email, reason, created_at) "
                        "VALUES (:email,:reason,:created_at)"
                    ),
                    {
                        "email": normalized,
                        "reason": reason[:240],
                        "created_at": self._now(),
                    },
                )

    def count_live_sends_last_24h(self) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with engine.begin() as conn:
            value = conn.execute(
                text(
                    "SELECT COUNT(*) FROM outreach_sends "
                    "WHERE dry_run=0 AND status='sent' AND created_at>=:since"
                ),
                {"since": since},
            ).scalar_one()
        return int(value or 0)

    def log_send(
        self,
        *,
        prospect_id: str,
        email: str,
        account: str,
        subject: str,
        status: str,
        idempotency_key: str,
        dry_run: bool,
        resend_id: str | None = None,
        error_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        record_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO outreach_sends "
                    "(id,prospect_id,email,account,subject,status,resend_id,"
                    "idempotency_key,dry_run,error_text,metadata_json,created_at) "
                    "VALUES (:id,:prospect_id,:email,:account,:subject,:status,"
                    ":resend_id,:idempotency_key,:dry_run,:error_text,"
                    ":metadata_json,:created_at)"
                ),
                {
                    "id": record_id,
                    "prospect_id": prospect_id,
                    "email": email.strip().lower(),
                    "account": account,
                    "subject": subject,
                    "status": status,
                    "resend_id": resend_id,
                    "idempotency_key": idempotency_key,
                    "dry_run": 1 if dry_run else 0,
                    "error_text": (error_text or "")[:2000] or None,
                    "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
                    "created_at": self._now(),
                },
            )
        return record_id


store = OutreachStore()

__all__ = ["OutreachStore", "store"]

"""Durable outreach suppression, send ledger, and engagement events.

Schema ownership belongs exclusively to Alembic. Runtime code only reads and
writes the tables introduced by outreach migrations 017 and 018.
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

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

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

    def count_live_sends(self) -> int:
        with engine.begin() as conn:
            value = conn.execute(
                text("SELECT COUNT(*) FROM outreach_sends WHERE dry_run=0 AND status='sent'")
            ).scalar_one()
        return int(value or 0)

    def count_trackable_live_sends(self) -> int:
        """Count only sends whose HTML actually contains first-party tracking.

        Historical sends created before engagement tracking launched must not
        dilute open or click rates. Metadata parsing stays database-portable
        across SQLite and PostgreSQL instead of relying on vendor JSON syntax.
        """
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT metadata_json FROM outreach_sends "
                    "WHERE dry_run=0 AND status='sent'"
                )
            ).all()
        return sum(
            1
            for row in rows
            if self._parse_json(row[0] if row else None).get("engagement_tracking") is True
        )

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
        record_id: str | None = None,
    ) -> str:
        send_id = (record_id or str(uuid.uuid4())).strip()
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
                    "id": send_id,
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
        return send_id

    def get_send(self, send_id: str) -> dict[str, Any] | None:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, prospect_id, email, account, subject, status, resend_id, "
                    "dry_run, metadata_json, created_at "
                    "FROM outreach_sends WHERE id=:send_id"
                ),
                {"send_id": send_id.strip()},
            ).mappings().first()
        if row is None:
            return None
        item = dict(row)
        item["dry_run"] = bool(item.get("dry_run"))
        item["metadata"] = self._parse_json(item.pop("metadata_json", None))
        return item

    def recent_sends(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, prospect_id, email, account, subject, status, resend_id, "
                    "dry_run, error_text, metadata_json, created_at "
                    "FROM outreach_sends ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings().all()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["dry_run"] = bool(item.get("dry_run"))
            item["metadata"] = self._parse_json(item.pop("metadata_json", None))
            items.append(item)
        return items

    def log_event(
        self,
        *,
        send_id: str,
        event_type: str,
        link_key: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        send = self.get_send(send_id)
        if not send or send.get("status") != "sent" or bool(send.get("dry_run")):
            return None
        event_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO outreach_events "
                    "(id,send_id,event_type,link_key,user_agent,metadata_json,created_at) "
                    "VALUES (:id,:send_id,:event_type,:link_key,:user_agent,:metadata_json,:created_at)"
                ),
                {
                    "id": event_id,
                    "send_id": send_id,
                    "event_type": event_type[:96],
                    "link_key": (link_key or "")[:32] or None,
                    "user_agent": (user_agent or "")[:500] or None,
                    "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
                    "created_at": self._now(),
                },
            )
        return event_id

    def recent_events(self, *, limit: int = 250) -> list[dict[str, Any]]:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT e.id, e.send_id, e.event_type, e.link_key, e.user_agent, "
                    "e.metadata_json, e.created_at, s.prospect_id, s.email, s.account, "
                    "s.subject, s.resend_id "
                    "FROM outreach_events e "
                    "JOIN outreach_sends s ON s.id=e.send_id "
                    "ORDER BY e.created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings().all()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = self._parse_json(item.pop("metadata_json", None))
            items.append(item)
        return items

    def engagement_summary(self, *, limit: int = 10_000) -> dict[str, Any]:
        sent_total_all_time = self.count_live_sends()
        trackable_sent_total = self.count_trackable_live_sends()
        events = self.recent_events(limit=limit)
        prospects: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}

        for event in reversed(events):
            event_type = str(event.get("event_type") or "unknown")
            counts[event_type] = counts.get(event_type, 0) + 1
            send_id = str(event.get("send_id") or "").strip()
            if not send_id:
                continue
            row = prospects.setdefault(
                send_id,
                {
                    "send_id": send_id,
                    "prospect_id": event.get("prospect_id"),
                    "email": event.get("email"),
                    "account": event.get("account"),
                    "subject": event.get("subject"),
                    "resend_id": event.get("resend_id"),
                    "open_signals": 0,
                    "clicks": 0,
                    "clicked_links": [],
                    "first_event_at": event.get("created_at"),
                    "last_event_at": event.get("created_at"),
                },
            )
            row["last_event_at"] = event.get("created_at")
            if event_type == "first_party.opened":
                row["open_signals"] += 1
            if event_type.startswith("first_party.clicked."):
                row["clicks"] += 1
                link = event.get("link_key")
                if link and link not in row["clicked_links"]:
                    row["clicked_links"].append(link)

        ranked = sorted(
            prospects.values(),
            key=lambda row: (row["clicks"], row["open_signals"], row["last_event_at"] or ""),
            reverse=True,
        )
        unique_opened = sum(1 for row in ranked if row["open_signals"] > 0)
        unique_clicked = sum(1 for row in ranked if row["clicks"] > 0)
        total_open_signals = sum(row["open_signals"] for row in ranked)
        total_clicks = sum(row["clicks"] for row in ranked)
        click_counts = {
            key: counts.get(f"first_party.clicked.{key}", 0)
            for key in ("portal", "meeting", "video")
        }

        return {
            "sent_total_all_time": sent_total_all_time,
            "trackable_sent_total": trackable_sent_total,
            "measurement_denominator": "trackable_sent_total",
            "unique_open_signal_sends": unique_opened,
            "unique_clicked_sends": unique_clicked,
            "total_open_signals": total_open_signals,
            "total_clicks": total_clicks,
            "open_signal_rate_percent": round((unique_opened / trackable_sent_total * 100), 2) if trackable_sent_total else 0.0,
            "click_through_rate_percent": round((unique_clicked / trackable_sent_total * 100), 2) if trackable_sent_total else 0.0,
            "click_counts": click_counts,
            "event_counts": counts,
            "engaged_prospects": ranked,
            "measurement_note": (
                "Rates include only live sends whose HTML contained first-party tracking. Historical untracked sends are excluded. "
                "Open signals remain approximate because email clients and privacy proxies may prefetch or block images; CTA clicks are stronger intent signals."
            ),
        }


store = OutreachStore()

__all__ = ["OutreachStore", "store"]

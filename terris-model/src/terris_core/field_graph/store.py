from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


class FieldGraphStore:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("TERRIS_FIELD_GRAPH_DSN", "")
        if not self.dsn:
            raise RuntimeError("TERRIS_FIELD_GRAPH_DSN is required")

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def append_event(self, tenant_id: str, event: dict[str, Any]) -> dict[str, Any]:
        required = ["event_type", "field_id", "truth_label", "source", "payload"]
        missing = [key for key in required if key not in event]
        if missing:
            raise ValueError(f"missing Field Graph event fields: {missing}")
        event_id = event.get("event_id") or str(uuid.uuid4())
        idempotency_key = event.get("idempotency_key") or hashlib.sha256(
            json.dumps({"tenant_id": tenant_id, "event_id": event_id, "payload": event["payload"]}, sort_keys=True).encode()
        ).hexdigest()
        observed_at = event.get("observed_at") or datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO terris_field_events
                  (tenant_id,event_id,idempotency_key,event_type,field_id,crop_cycle_id,truth_label,source,observed_at,payload,provenance,training_consent)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                ON CONFLICT (tenant_id,idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key
                RETURNING *
                """,
                (
                    tenant_id, event_id, idempotency_key, event["event_type"], event["field_id"], event.get("crop_cycle_id"),
                    event["truth_label"], event["source"], observed_at, json.dumps(event["payload"]),
                    json.dumps(event.get("provenance", {})), bool(event.get("training_consent", False)),
                ),
            ).fetchone()
            conn.commit()
        return dict(row)

    def field_state(self, tenant_id: str, field_id: str, limit: int = 250) -> dict[str, Any]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_id,event_type,field_id,crop_cycle_id,truth_label,source,observed_at,payload,provenance,training_consent,created_at
                FROM terris_field_events
                WHERE tenant_id=%s AND field_id=%s
                ORDER BY observed_at DESC, created_at DESC
                LIMIT %s
                """,
                (tenant_id, field_id, limit),
            ).fetchall()
        return {"field_id": field_id, "events": [dict(row) for row in rows], "event_count": len(rows)}

    def training_export(self, tenant_id: str, limit: int = 10000) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_id,event_type,field_id,crop_cycle_id,truth_label,source,observed_at,payload,provenance
                FROM terris_field_events
                WHERE tenant_id=%s AND training_consent=TRUE
                ORDER BY observed_at ASC
                LIMIT %s
                """,
                (tenant_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

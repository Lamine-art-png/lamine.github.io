from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


_OPERATIONAL_TASKS = {"irrigation_plan", "irrigation_recommendation", "decision_workbench", "field_diagnosis", "execution", "action"}
_DEFAULT_OPERATIONAL_MAX_AGE_SECONDS = {
    "telemetry": 24 * 3600,
    "telemetry_recent": 24 * 3600,
    "sensor": 24 * 3600,
    "weather": 12 * 3600,
    "forecast": 12 * 3600,
    "controller_event": 24 * 3600,
    "recommendation_recent": 24 * 3600,
    "uploaded_record": 72 * 3600,
}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _policy() -> dict[str, int]:
    policy = dict(_DEFAULT_OPERATIONAL_MAX_AGE_SECONDS)
    raw = os.getenv("INTELLIGENCE_FRESHNESS_POLICY_JSON", "").strip()
    if not raw:
        return policy
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return policy
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            try:
                seconds = int(value)
            except (TypeError, ValueError):
                continue
            if seconds > 0:
                policy[str(key)] = seconds
    return policy


def _observed_at(item: dict[str, Any]) -> datetime | None:
    metadata = item.get("metadata_json") or item.get("metadata") or {}
    for value in (
        item.get("occurred_at"),
        item.get("source_updated_at"),
        item.get("timestamp"),
        metadata.get("observed_at") if isinstance(metadata, dict) else None,
        metadata.get("source_updated_at") if isinstance(metadata, dict) else None,
        item.get("created_at"),
    ):
        parsed = _parse_time(value)
        if parsed is not None:
            return parsed
    return None


def evaluate_evidence_freshness(*, task: str, evidence: list[Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    operational = task in _OPERATIONAL_TASKS or "irrig" in task.lower() or "execut" in task.lower()
    policy = _policy()
    rows: list[dict[str, Any]] = []
    blocking_count = 0

    for item in evidence:
        if not isinstance(item, dict):
            continue
        evidence_type = str(item.get("type") or item.get("evidence_type") or item.get("source_type") or "unknown")
        source_id = str(item.get("id") or item.get("source_id") or item.get("filename") or evidence_type)
        max_age = policy.get(evidence_type)
        if max_age is None:
            for key, seconds in policy.items():
                if key in evidence_type.lower():
                    max_age = seconds
                    break
        observed = _observed_at(item)
        if not operational or max_age is None:
            status = "not_required"
            blocking = False
            age_seconds = None if observed is None else max(0, int((current - observed).total_seconds()))
        elif observed is None:
            status = "unknown"
            blocking = True
            age_seconds = None
        else:
            age_seconds = max(0, int((current - observed).total_seconds()))
            status = "fresh" if age_seconds <= max_age else "stale"
            blocking = status == "stale"
        if blocking:
            blocking_count += 1
        rows.append({
            "source_id": source_id,
            "evidence_type": evidence_type,
            "observed_at": observed.isoformat() if observed else None,
            "age_seconds": age_seconds,
            "max_age_seconds": max_age,
            "status": status,
            "blocking": blocking,
        })

    return {
        "task": task,
        "operational": operational,
        "blocking_count": blocking_count,
        "evaluated_count": len(rows),
        "records": rows[:100],
    }

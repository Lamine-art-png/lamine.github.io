"""Per-field Crop Intelligence summary: what changed, how fresh, what next.

Built from already-serialized Field Intelligence observations for one field
(newest first), so it reuses the existing tenant-scoped query and adds no
storage. Changes are reported only when the evidence supports them:
detection counts change only when their observed bounds do not overlap, and
an assessment that conflicts with a recent one is flagged rather than
silently replacing it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

SUMMARY_VERSION = "crop-condition-summary/1"
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
FRESH_HOURS = 72
STALE_HOURS = 14 * 24
CONFLICT_WINDOW_HOURS = 48
_UNHEALTHY = {"stressed", "damaged"}
_HEALTHY = {"healthy", "mostly_healthy"}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _observed_at(observation: dict[str, Any]) -> datetime | None:
    return _parse_time(observation.get("occurred_at") or observation.get("observed_at") or observation.get("created_at"))


def freshness(age_hours: float | None) -> str:
    if age_hours is None:
        return "unknown"
    if age_hours <= FRESH_HOURS:
        return "fresh"
    if age_hours <= STALE_HOURS:
        return "aging"
    return "stale"


def _vision(observation: dict[str, Any]) -> dict[str, Any]:
    structured = observation.get("structured") if isinstance(observation.get("structured"), dict) else {}
    vision = structured.get("vision") if isinstance(structured.get("vision"), dict) else {}
    return vision


def _detection_totals(observation: dict[str, Any]) -> dict[str, tuple[int, int]]:
    structured = observation.get("structured") if isinstance(observation.get("structured"), dict) else {}
    detections = structured.get("detections") if isinstance(structured.get("detections"), dict) else {}
    totals = (detections.get("counts") or {}).get("totals") or []
    return {
        str(row["label"]): (int(row.get("observed_lower_bound") or 0), int(row.get("sum_upper_bound") or 0))
        for row in totals if isinstance(row, dict) and row.get("label")
    }


def _issues(observation: dict[str, Any]) -> set[str]:
    return {str(item).strip().lower() for item in _vision(observation).get("possible_issues") or [] if str(item).strip()}


def _snapshot(observation: dict[str, Any], now: datetime) -> dict[str, Any]:
    observed = _observed_at(observation)
    age = round((now - observed).total_seconds() / 3600, 1) if observed else None
    vision = _vision(observation)
    detections = _detection_totals(observation)
    return {
        "observation_id": observation.get("id"),
        "observed_at": observed.isoformat() if observed else None,
        "age_hours": age,
        "freshness": freshness(age),
        "block_name": observation.get("block_name"),
        "severity": observation.get("severity") or "info",
        "status": observation.get("status"),
        "summary": observation.get("summary"),
        "recommended_action": observation.get("recommended_action"),
        "review_required": observation.get("status") == "needs_review" or bool(vision),
        "visual": None if not vision else {
            "analysis_state": vision.get("analysis_state", "structured"),
            "crop_condition": vision.get("crop_condition"),
            "confidence": vision.get("confidence"),
            "confidence_kind": vision.get("confidence_kind"),
            "safety_flags": list(vision.get("safety_flags") or []),
            "media_analyzed": vision.get("images_analyzed"),
        },
        "detections": [
            {"label": label, "observed_lower_bound": low, "sum_upper_bound": high}
            for label, (low, high) in sorted(detections.items())
        ],
        "task_ids": list(observation.get("task_ids") or []),
    }


def _changes(latest: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if previous is None:
        return changes
    latest_rank = SEVERITY_RANK.get(str(latest.get("severity") or "info"), 0)
    previous_rank = SEVERITY_RANK.get(str(previous.get("severity") or "info"), 0)
    if latest_rank != previous_rank:
        changes.append({
            "kind": "severity_increased" if latest_rank > previous_rank else "severity_decreased",
            "from": previous.get("severity") or "info", "to": latest.get("severity") or "info",
        })
    new_issues = sorted(_issues(latest) - _issues(previous))
    if new_issues:
        changes.append({"kind": "new_visible_issue", "issues": new_issues[:10]})
    no_longer = sorted(_issues(previous) - _issues(latest))
    if no_longer:
        changes.append({"kind": "issue_not_seen_again", "issues": no_longer[:10],
                        "note": "Not seen in the latest evidence; confirm in the field before closing."})
    latest_counts, previous_counts = _detection_totals(latest), _detection_totals(previous)
    for label in sorted(set(latest_counts) & set(previous_counts)):
        (low_now, high_now), (low_before, high_before) = latest_counts[label], previous_counts[label]
        if low_now > high_before or high_now < low_before:
            changes.append({"kind": "detection_count_changed", "label": label,
                            "previous_bounds": [low_before, high_before], "latest_bounds": [low_now, high_now]})
    latest_time, previous_time = _observed_at(latest), _observed_at(previous)
    latest_condition = _vision(latest).get("crop_condition")
    previous_condition = _vision(previous).get("crop_condition")
    if latest_time and previous_time and (latest_time - previous_time).total_seconds() <= CONFLICT_WINDOW_HOURS * 3600:
        if (latest_condition in _HEALTHY and previous_condition in _UNHEALTHY) or (
            latest_condition in _UNHEALTHY and previous_condition in _HEALTHY
        ):
            changes.append({
                "kind": "conflicting_recent_assessments", "previous": previous_condition, "latest": latest_condition,
                "note": "Two assessments within 48 hours disagree; verify in the field before acting.",
            })
    return changes


def field_condition_summary(
    observations: Iterable[dict[str, Any]], *, field_id: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = [row for row in observations if row.get("status") != "deleted"]
    rows.sort(key=lambda row: _observed_at(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if not rows:
        return {"summary_version": SUMMARY_VERSION, "field_id": field_id, "status": "no_observations",
                "observations_considered": 0, "latest": None, "changes": [], "trend": [], "open_reviews": 0}
    latest = _snapshot(rows[0], now)
    changes = _changes(rows[0], rows[1] if len(rows) > 1 else None)
    if latest["freshness"] == "stale":
        changes.append({"kind": "stale_evidence", "age_hours": latest["age_hours"],
                        "note": "The newest evidence is more than 14 days old."})
    next_action = latest.get("recommended_action")
    if not next_action and latest["review_required"]:
        next_action = "Review the latest observation and confirm the visible findings in the field."
    return {
        "summary_version": SUMMARY_VERSION,
        "field_id": field_id,
        "status": "ok",
        "observations_considered": len(rows),
        "latest": latest,
        "changes": changes,
        "open_reviews": sum(1 for row in rows if row.get("status") == "needs_review"),
        "next_action": next_action,
        "trend": [
            {"observation_id": row.get("id"), "observed_at": (_observed_at(row) or now).isoformat(),
             "severity": row.get("severity") or "info", "status": row.get("status")}
            for row in rows[:20]
        ],
    }

"""Per-field Crop Intelligence summary: what changed, how fresh, what next.

Built from already-serialized Field Intelligence observations for one field,
so it reuses the existing tenant-scoped query and adds no storage.

A change over time is claimed only between *comparable* observations: the
same block (or both unscoped to a block) captured by the same method
(visual evidence versus a spoken or typed report). Detection counts are
compared only when the label was counted the same way over the same number
of frames, and only when their observed bounds do not overlap. Differences
between blocks are reported separately as a field-level snapshot, never as a
trend. Records dated in the future are excluded and listed rather than
treated as the freshest evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SUMMARY_VERSION = "crop-condition-summary/3"
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
FRESH_HOURS = 72
STALE_HOURS = 14 * 24
CONFLICT_WINDOW_HOURS = 48
FUTURE_TOLERANCE = timedelta(minutes=5)  # device clock skew allowance
_UNHEALTHY = {"stressed", "damaged"}
_HEALTHY = {"healthy", "mostly_healthy"}
UNSCOPED_BLOCK = "__field__"
_SNAPSHOT_NOTE = "Newest observation per block; differences between blocks are not a trend."


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
    if age_hours < -FUTURE_TOLERANCE.total_seconds() / 3600:
        return "future_dated"
    if age_hours <= FRESH_HOURS:
        return "fresh"
    if age_hours <= STALE_HOURS:
        return "aging"
    return "stale"


def _structured(observation: dict[str, Any]) -> dict[str, Any]:
    return observation.get("structured") if isinstance(observation.get("structured"), dict) else {}


def _vision(observation: dict[str, Any]) -> dict[str, Any]:
    vision = _structured(observation).get("vision")
    return vision if isinstance(vision, dict) else {}


def block_key(observation: dict[str, Any]) -> str:
    block_id = str(observation.get("block_id") or "").strip()
    if block_id:
        return f"id:{block_id}"
    name = " ".join(str(observation.get("block_name") or "").casefold().split())
    return f"name:{name}" if name else UNSCOPED_BLOCK


def method_key(observation: dict[str, Any]) -> str:
    """How the evidence was captured: structured visual analysis or a report."""
    vision = _vision(observation)
    if vision and vision.get("analysis_state", "structured") == "structured":
        return "visual"
    return "report"


def _detection_counts(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-label bounds plus the coverage signature they were counted under."""
    detections = _structured(observation).get("detections")
    if not isinstance(detections, dict):
        return {}
    counts = detections.get("counts") if isinstance(detections.get("counts"), dict) else {}
    methods: dict[str, set[str]] = {}
    frames: dict[str, int] = {}
    for asset in counts.get("per_asset") or []:
        for label, row in (asset.get("counts") or {}).items():
            methods.setdefault(label, set()).add(str(row.get("count_method")))
            frames[label] = frames.get(label, 0) + int(row.get("frames_considered") or 0)
    result: dict[str, dict[str, Any]] = {}
    for row in counts.get("totals") or []:
        if not isinstance(row, dict) or not row.get("label"):
            continue
        label = str(row["label"])
        result[label] = {
            "bounds": (int(row.get("observed_lower_bound") or 0), int(row.get("sum_upper_bound") or 0)),
            "coverage": (tuple(sorted(methods.get(label, set()))), frames.get(label, 0)),
        }
    return result


def sampling_units(observation: dict[str, Any]) -> tuple[str, tuple[str, ...]] | None:
    """The sampling plan and unit ids (trees, vines, row segments) a count covered, if recorded.

    Equal frame counts do not establish equal spatial coverage: two walks
    through different rows can produce the same number of frames. A count is
    only comparable over time when both observations revisited the same
    planned sample units.
    """
    detections = _structured(observation).get("detections")
    plan = detections.get("sampling_plan") if isinstance(detections, dict) else None
    if not isinstance(plan, dict):
        return None
    plan_id = str(plan.get("plan_id") or "").strip()
    units = tuple(sorted({str(unit).strip() for unit in plan.get("unit_ids") or [] if str(unit).strip()}))
    return (plan_id, units) if plan_id and units else None


def _issues(observation: dict[str, Any]) -> set[str]:
    return {str(item).strip().lower() for item in _vision(observation).get("possible_issues") or [] if str(item).strip()}


def _snapshot(observation: dict[str, Any], now: datetime) -> dict[str, Any]:
    observed = _observed_at(observation)
    age = (now - observed).total_seconds() / 3600 if observed else None
    vision = _vision(observation)
    counts = _detection_counts(observation)
    return {
        "observation_id": observation.get("id"),
        "observed_at": observed.isoformat() if observed else None,
        "age_hours": round(age, 1) if age is not None else None,
        "freshness": freshness(age),  # judged on the exact age, not the rounded display value
        "block_key": block_key(observation),
        "block_name": observation.get("block_name"),
        "method": method_key(observation),
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
            {"label": label, "observed_lower_bound": row["bounds"][0], "sum_upper_bound": row["bounds"][1]}
            for label, row in sorted(counts.items())
        ],
        "task_ids": list(observation.get("task_ids") or []),
    }


def _changes(latest: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    """Changes between two comparable observations (same block and method)."""
    changes: list[dict[str, Any]] = []
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
    latest_counts, previous_counts = _detection_counts(latest), _detection_counts(previous)
    latest_units = sampling_units(latest)
    same_units = latest_units is not None and latest_units == sampling_units(previous)
    for label in sorted(set(latest_counts) & set(previous_counts)):
        now_row, before_row = latest_counts[label], previous_counts[label]
        (low_now, high_now), (low_before, high_before) = now_row["bounds"], before_row["bounds"]
        if not (low_now > high_before or high_now < low_before):
            continue  # overlapping bounds: no supported difference
        entry = {"label": label, "previous_bounds": [low_before, high_before], "latest_bounds": [low_now, high_now]}
        if now_row["coverage"] == before_row["coverage"] and same_units:
            changes.append({"kind": "detection_count_changed", **entry, "trend": True, "basis": "same_sampling_units"})
        else:
            changes.append({
                "kind": "different_observation_count", **entry, "trend": False,
                "reason": ("count_method_or_frames_differ" if now_row["coverage"] != before_row["coverage"]
                           else "spatial_coverage_not_established"),
                "note": "The observations did not count the same sample units the same way; this is not a trend.",
            })
    latest_time, previous_time = _observed_at(latest), _observed_at(previous)
    latest_condition = _vision(latest).get("crop_condition")
    previous_condition = _vision(previous).get("crop_condition")
    if latest_time and previous_time and (latest_time - previous_time).total_seconds() <= CONFLICT_WINDOW_HOURS * 3600:
        if (latest_condition in _HEALTHY and previous_condition in _UNHEALTHY) or (
            latest_condition in _UNHEALTHY and previous_condition in _HEALTHY
        ):
            changes.append({
                "kind": "conflicting_recent_assessments", "previous": previous_condition, "latest": latest_condition,
                "note": "Two assessments of the same block within 48 hours disagree; verify in the field before acting.",
            })
    return changes


def field_condition_summary(
    observations: Iterable[dict[str, Any]], *, field_id: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = [row for row in observations if row.get("status") != "deleted"]
    future = [row for row in rows if (_observed_at(row) or now) > now + FUTURE_TOLERANCE]
    future_ids = {id(row) for row in future}
    rows = [row for row in rows if id(row) not in future_ids]
    rows.sort(key=lambda row: _observed_at(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    excluded = [{"observation_id": row.get("id"), "observed_at": (_observed_at(row) or now).isoformat(),
                 "reason": "future_dated"} for row in future]
    if not rows:
        return {"summary_version": SUMMARY_VERSION, "field_id": field_id, "status": "no_observations",
                "observations_considered": 0, "latest": None, "comparison": {"basis": "no_comparable_prior"},
                "changes": [], "field_snapshot": {"note": _SNAPSHOT_NOTE, "blocks": []}, "timeline": [],
                "open_reviews": 0, "excluded": excluded}

    latest_row = rows[0]
    latest = _snapshot(latest_row, now)
    previous_row = next(
        (row for row in rows[1:] if block_key(row) == latest["block_key"] and method_key(row) == latest["method"]),
        None,
    )
    changes = _changes(latest_row, previous_row) if previous_row is not None else []
    for change in changes:
        change["scope"] = "same_block_same_method"
    if latest["freshness"] == "stale":
        changes.append({"kind": "stale_evidence", "age_hours": latest["age_hours"],
                        "note": "The newest evidence is more than 14 days old."})
    if excluded:
        changes.append({"kind": "future_dated_records_excluded", "count": len(excluded),
                        "note": "Records dated in the future were left out; check the capture device clock."})

    # Newest observation per block: a field-level picture, not a trend.
    snapshot: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = block_key(row)
        if key not in snapshot:
            snapshot[key] = {"block_key": key, "block_name": row.get("block_name"), "observation_id": row.get("id"),
                             "observed_at": (_observed_at(row) or now).isoformat(), "severity": row.get("severity") or "info",
                             "method": method_key(row), "status": row.get("status")}

    next_action = latest.get("recommended_action")
    if not next_action and latest["review_required"]:
        next_action = "Review the latest observation and confirm the visible findings in the field."
    return {
        "summary_version": SUMMARY_VERSION,
        "field_id": field_id,
        "status": "ok",
        "observations_considered": len(rows),
        "latest": latest,
        "comparison": (
            {"basis": "same_block_same_method", "previous_observation_id": previous_row.get("id"),
             "block_key": latest["block_key"], "method": latest["method"]}
            if previous_row is not None else {"basis": "no_comparable_prior"}
        ),
        "changes": changes,
        "field_snapshot": {"note": _SNAPSHOT_NOTE, "blocks": list(snapshot.values())},
        "open_reviews": sum(1 for row in rows if row.get("status") == "needs_review"),
        "next_action": next_action,
        "timeline": [
            {"observation_id": row.get("id"), "observed_at": (_observed_at(row) or now).isoformat(),
             "block_key": block_key(row), "method": method_key(row),
             "severity": row.get("severity") or "info", "status": row.get("status")}
            for row in rows[:20]
        ],
        "excluded": excluded,
    }

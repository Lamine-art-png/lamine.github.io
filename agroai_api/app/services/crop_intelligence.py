"""Per-field Crop Intelligence summary: what changed, how fresh, what next.

Built from already-serialized Field Intelligence observations for one field,
so it reuses the existing tenant-scoped query and adds no storage.

Only completed crop assessments (observation, issue and pest/disease
records that have finished processing) are compared, and only within one
named block captured by the same method (analysed visual evidence, visual
media that was not analysed, or a spoken or typed report). Observations
with no block are never paired: two of them may describe opposite ends of
the field. A difference is called a trend only when both observations
revisited the same planned sample units; otherwise it is reported as a
difference between observations that may cover different parts of the
block. Detection counts are compared only when the label was counted the
same way over the same number of frames, and only when their observed
bounds do not overlap. Differences between blocks are reported separately
as a field-level snapshot, never as a trend. Records dated in the future
are excluded and listed rather than treated as the freshest evidence.
Records edited through PATCH can hold any JSON, so every structured field
is type-checked before use.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SUMMARY_VERSION = "crop-condition-summary/4"
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
FRESH_HOURS = 72
STALE_HOURS = 14 * 24
CONFLICT_WINDOW_HOURS = 48
FUTURE_TOLERANCE = timedelta(minutes=5)  # device clock skew allowance
_UNHEALTHY = {"stressed", "damaged"}
_HEALTHY = {"healthy", "mostly_healthy"}
UNSCOPED_BLOCK = "__field__"
_SNAPSHOT_NOTE = "Newest observation per block; differences between blocks are not a trend."
# Not finished processing: no assessment to compare yet.
PENDING_STATUSES = {"received", "staged", "queued", "processing", "failed"}
# Event types that assess the crop; irrigation, meter, equipment and note records do not.
ASSESSMENT_EVENT_TYPES = {"observation", "issue", "pest_disease"}
_VISUAL_ASSET_KINDS = {"photo", "video"}
_GONE_ASSET_STATUSES = {"deleted", "pending_deletion"}
_NOT_A_TREND = "The observations may cover different parts of the block; this is not a trend."


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float) and math.isfinite(value):
        return max(int(value), 0)
    return 0


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


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
    return _as_dict(observation.get("structured"))


def _vision(observation: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_structured(observation).get("vision"))


def severity(observation: dict[str, Any]) -> str | None:
    """Normalized severity; ``None`` when the stored value is not on the scale."""
    value = observation.get("severity")
    if value is None or (isinstance(value, str) and not value.strip()):
        return "info"
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in SEVERITY_RANK else None


def has_evidence(observation: dict[str, Any]) -> bool:
    """Words (a transcript, a correction or a summary) or visual media to assess.

    A voice note whose transcription was unavailable or failed, with no media,
    still finishes processing, but it says nothing about the crop.
    """
    return bool(
        _text(observation.get("corrected_transcript")) or _text(observation.get("transcript"))
        or _text(observation.get("summary")) or method_key(observation) != "report"
    )


def is_assessment(observation: dict[str, Any]) -> bool:
    """A finished record with evidence that assesses the crop (a missing event type is an observation)."""
    event_type = observation.get("event_type") or "observation"
    return (observation.get("status") not in PENDING_STATUSES and event_type in ASSESSMENT_EVENT_TYPES
            and has_evidence(observation))


def block_key(observation: dict[str, Any]) -> str:
    block_id = str(observation.get("block_id") or "").strip()
    if block_id:
        return f"id:{block_id}"
    name = " ".join(str(observation.get("block_name") or "").casefold().split())
    return f"name:{name}" if name else UNSCOPED_BLOCK


def method_key(observation: dict[str, Any]) -> str:
    """How the evidence was captured.

    ``visual``: structured analysis of photos or video; ``visual_unassessed``:
    photos or video whose analysis is missing, degraded, or predates the
    analysis contract (no ``analysis_state``: older records include prose the
    provider returned instead of an analysis); ``report``: a spoken or typed
    account with no visual media.
    """
    vision = _vision(observation)
    if vision.get("analysis_state") == "structured":
        return "visual"
    media = [asset for asset in _as_list(observation.get("assets")) if isinstance(asset, dict)
             and asset.get("kind") in _VISUAL_ASSET_KINDS and asset.get("status") not in _GONE_ASSET_STATUSES]
    if vision or media:
        return "visual_unassessed"
    return "report"


def _detection_counts(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-label bounds plus the coverage signature they were counted under."""
    counts = _as_dict(_as_dict(_structured(observation).get("detections")).get("counts"))
    methods: dict[str, set[str]] = {}
    frames: dict[str, int] = {}
    for asset in _as_list(counts.get("per_asset")):
        for label, row in _as_dict(_as_dict(asset).get("counts")).items():
            row = _as_dict(row)
            methods.setdefault(str(label), set()).add(str(row.get("count_method")))
            frames[str(label)] = frames.get(str(label), 0) + _count(row.get("frames_considered"))
    result: dict[str, dict[str, Any]] = {}
    for row in _as_list(counts.get("totals")):
        label = _text(_as_dict(row).get("label"))
        if label is None:
            continue
        result[label] = {
            "bounds": (_count(row.get("observed_lower_bound")), _count(row.get("sum_upper_bound"))),
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
    plan = _as_dict(_as_dict(_structured(observation).get("detections")).get("sampling_plan"))
    plan_id = _text(plan.get("plan_id"))
    units = tuple(sorted({unit.strip() for unit in _as_list(plan.get("unit_ids")) if _text(unit)}))
    return (plan_id, units) if plan_id and units else None


def same_sampling_units(latest: dict[str, Any], previous: dict[str, Any]) -> bool:
    units = sampling_units(latest)
    return units is not None and units == sampling_units(previous)


def _issues(observation: dict[str, Any]) -> set[str]:
    return {item.strip().lower() for item in _as_list(_vision(observation).get("possible_issues")) if _text(item)}


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
        "event_type": observation.get("event_type") or "observation",
        "severity": severity(observation) or "unrecognized",
        "status": observation.get("status"),
        "summary": observation.get("summary"),
        "recommended_action": observation.get("recommended_action"),
        "review_required": observation.get("status") == "needs_review" or bool(vision),
        "visual": None if not vision else {
            "analysis_state": _text(vision.get("analysis_state")) or "legacy_unverified",
            "crop_condition": _text(vision.get("crop_condition")),
            "confidence": vision.get("confidence"),
            "confidence_kind": vision.get("confidence_kind"),
            "safety_flags": [flag for flag in _as_list(vision.get("safety_flags")) if _text(flag)],
            "media_analyzed": vision.get("images_analyzed"),
        },
        "detections": [
            {"label": label, "observed_lower_bound": row["bounds"][0], "sum_upper_bound": row["bounds"][1]}
            for label, row in sorted(counts.items())
        ],
        "task_ids": list(_as_list(observation.get("task_ids"))),
    }


def _changes(latest: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    """Changes between two comparable observations (same block and method).

    A change is a trend only when both observations revisited the same
    planned sample units; otherwise it is a difference between observations
    that may cover different parts of the block.
    """
    changes: list[dict[str, Any]] = []
    same_units = same_sampling_units(latest, previous)
    trend = {"trend": True, "basis": "same_sampling_units"}
    no_trend = {"trend": False, "reason": "spatial_coverage_not_established", "note": _NOT_A_TREND}
    latest_severity, previous_severity = severity(latest), severity(previous)
    if latest_severity and previous_severity and latest_severity != previous_severity:
        entry = {"from": previous_severity, "to": latest_severity}
        if same_units:
            increased = SEVERITY_RANK[latest_severity] > SEVERITY_RANK[previous_severity]
            changes.append({"kind": "severity_increased" if increased else "severity_decreased", **entry, **trend})
        else:
            changes.append({"kind": "severity_differs", **entry, **no_trend})
    new_issues = sorted(_issues(latest) - _issues(previous))
    if new_issues:
        changes.append({"kind": "new_visible_issue", "issues": new_issues[:10], **trend} if same_units
                       else {"kind": "issue_seen_only_in_latest", "issues": new_issues[:10], **no_trend})
    no_longer = sorted(_issues(previous) - _issues(latest))
    if no_longer:
        confirm = "Not seen in the latest evidence; confirm in the field before closing."
        changes.append({"kind": "issue_not_seen_again", "issues": no_longer[:10], **trend, "note": confirm} if same_units
                       else {"kind": "issue_seen_only_in_previous", "issues": no_longer[:10], **no_trend,
                             "note": f"{confirm} {_NOT_A_TREND}"})
    latest_counts, previous_counts = _detection_counts(latest), _detection_counts(previous)
    for label in sorted(set(latest_counts) & set(previous_counts)):
        now_row, before_row = latest_counts[label], previous_counts[label]
        (low_now, high_now), (low_before, high_before) = now_row["bounds"], before_row["bounds"]
        if not (low_now > high_before or high_now < low_before):
            continue  # overlapping bounds: no supported difference
        entry = {"label": label, "previous_bounds": [low_before, high_before], "latest_bounds": [low_now, high_now]}
        if now_row["coverage"] == before_row["coverage"] and same_units:
            changes.append({"kind": "detection_count_changed", **entry, **trend})
        else:
            changes.append({
                "kind": "different_observation_count", **entry, "trend": False,
                "reason": ("count_method_or_frames_differ" if now_row["coverage"] != before_row["coverage"]
                           else "spatial_coverage_not_established"),
                "note": "The observations did not count the same sample units the same way; this is not a trend.",
            })
    latest_time, previous_time = _observed_at(latest), _observed_at(previous)
    latest_condition = _text(_vision(latest).get("crop_condition"))
    previous_condition = _text(_vision(previous).get("crop_condition"))
    if latest_time and previous_time and (latest_time - previous_time).total_seconds() <= CONFLICT_WINDOW_HOURS * 3600:
        if (latest_condition in _HEALTHY and previous_condition in _UNHEALTHY) or (
            latest_condition in _UNHEALTHY and previous_condition in _HEALTHY
        ):
            changes.append({
                "kind": "conflicting_recent_assessments", "previous": previous_condition, "latest": latest_condition,
                "spatial_coverage": "same_sampling_units" if same_units else "not_established",
                "note": ("Two assessments of the same block within 48 hours disagree; verify in the field before acting."
                         if same_units else
                         "Two assessments of the same block within 48 hours disagree; they may show different parts "
                         "of the block. Verify in the field before acting."),
            })
    return changes


def _comparison(latest_row: dict[str, Any], previous_row: dict[str, Any] | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not is_assessment(latest_row):
        return {"basis": "no_comparable_prior", "reason": "no_completed_crop_assessment"}
    if block_key(latest_row) == UNSCOPED_BLOCK:
        return {"basis": "no_comparable_prior", "reason": "observation_has_no_block"}
    if previous_row is None:
        # Only the records read are searched; an older prior may exist outside them.
        return {"basis": "no_comparable_prior", "reason": "no_prior_assessment_of_this_block_by_this_method_in_window",
                "window_records": len(rows)}
    latest_time, previous_time = _observed_at(latest_row), _observed_at(previous_row)
    return {
        "basis": "same_block_same_method", "previous_observation_id": previous_row.get("id"),
        "block_key": block_key(latest_row), "method": method_key(latest_row),
        "previous_observed_at": previous_time.isoformat() if previous_time else None,
        "gap_hours": round((latest_time - previous_time).total_seconds() / 3600, 1) if latest_time and previous_time else None,
        "spatial_coverage": "same_sampling_units" if same_sampling_units(latest_row, previous_row) else "not_established",
    }


def field_condition_summary(
    observations: Iterable[dict[str, Any]], *, field_id: str | None = None, now: datetime | None = None,
    future_dated_total: int | None = None,
) -> dict[str, Any]:
    """``future_dated_total`` is the number of future-dated records in scope when
    the caller fetched only some of them."""
    now = now or datetime.now(timezone.utc)
    rows = [row for row in observations if isinstance(row, dict) and row.get("status") != "deleted"]
    future = [row for row in rows if (_observed_at(row) or now) > now + FUTURE_TOLERANCE]
    future_ids = {id(row) for row in future}
    rows = [row for row in rows if id(row) not in future_ids]
    rows.sort(key=lambda row: _observed_at(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    excluded = [{"observation_id": row.get("id"), "observed_at": (_observed_at(row) or now).isoformat(),
                 "reason": "future_dated"} for row in future]
    future_count = max(len(excluded), future_dated_total or 0)
    if not rows:
        return {"summary_version": SUMMARY_VERSION, "field_id": field_id, "status": "no_observations",
                "observations_considered": 0, "latest": None,
                "comparison": {"basis": "no_comparable_prior", "reason": "no_observations"},
                "changes": [], "field_snapshot": {"note": _SNAPSHOT_NOTE, "blocks": []}, "timeline": [],
                "open_reviews": 0, "pending_processing": 0, "excluded": excluded,
                "future_dated_excluded": future_count}

    assessments = [row for row in rows if is_assessment(row)]
    # The latest crop assessment; a newer pending or non-crop record is listed in the timeline only.
    latest_row = assessments[0] if assessments else rows[0]
    latest = _snapshot(latest_row, now)
    previous_row = None
    if is_assessment(latest_row) and latest["block_key"] != UNSCOPED_BLOCK:
        previous_row = next(
            (row for row in assessments[1:] if block_key(row) == latest["block_key"] and method_key(row) == latest["method"]),
            None,
        )
    changes = _changes(latest_row, previous_row) if previous_row is not None else []
    for change in changes:
        change["scope"] = "same_block_same_method"
    if latest["freshness"] == "stale":
        changes.append({"kind": "stale_evidence", "age_hours": latest["age_hours"],
                        "note": "The newest evidence is more than 14 days old."})
    if future_count:
        changes.append({"kind": "future_dated_records_excluded", "count": future_count,
                        "note": "Records dated in the future were left out; check the capture device clock."})

    # Newest crop assessment per block: a field-level picture, not a trend.
    snapshot: dict[str, dict[str, Any]] = {}
    for row in assessments:
        key = block_key(row)
        if key not in snapshot:
            snapshot[key] = {"block_key": key, "block_name": row.get("block_name"), "observation_id": row.get("id"),
                             "observed_at": (_observed_at(row) or now).isoformat(),
                             "severity": severity(row) or "unrecognized", "method": method_key(row),
                             "status": row.get("status")}

    next_action = _text(latest.get("recommended_action"))
    if not next_action and latest["review_required"]:
        next_action = "Review the latest observation and confirm the visible findings in the field."
    return {
        "summary_version": SUMMARY_VERSION,
        "field_id": field_id,
        "status": "ok",
        "observations_considered": len(rows),
        "latest": latest,
        "comparison": _comparison(latest_row, previous_row, rows),
        "changes": changes,
        "field_snapshot": {"note": _SNAPSHOT_NOTE, "blocks": list(snapshot.values())},
        "open_reviews": sum(1 for row in rows if row.get("status") == "needs_review"),
        "pending_processing": sum(1 for row in rows if row.get("status") in PENDING_STATUSES),
        "records_without_evidence": sum(1 for row in rows if not has_evidence(row)),
        "next_action": next_action,
        "timeline": [
            {"observation_id": row.get("id"), "observed_at": (_observed_at(row) or now).isoformat(),
             "block_key": block_key(row), "method": method_key(row), "event_type": row.get("event_type") or "observation",
             "severity": severity(row) or "unrecognized", "status": row.get("status")}
            for row in rows[:20]
        ],
        "excluded": excluded,
        "future_dated_excluded": future_count,
    }

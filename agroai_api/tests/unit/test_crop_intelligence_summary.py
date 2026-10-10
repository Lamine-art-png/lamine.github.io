from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.crop_intelligence import field_condition_summary, freshness

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _obs(obs_id, hours_ago, *, severity="low", status="completed", issues=(), condition=None, totals=None, action=None):
    structured = {}
    if issues or condition:
        structured["vision"] = {"possible_issues": list(issues), "crop_condition": condition, "analysis_state": "structured",
                                "confidence": None, "confidence_kind": "model_self_reported_uncalibrated"}
    if totals is not None:
        structured["detections"] = {"counts": {"totals": totals}}
    return {
        "id": obs_id, "occurred_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "severity": severity,
        "status": status, "summary": f"summary {obs_id}", "recommended_action": action, "structured": structured,
        "task_ids": [],
    }


def test_no_observations():
    summary = field_condition_summary([], field_id="f1", now=NOW)
    assert summary["status"] == "no_observations" and summary["latest"] is None


def test_freshness_bands():
    assert freshness(None) == "unknown"
    assert freshness(10) == "fresh"
    assert freshness(100) == "aging"
    assert freshness(24 * 15) == "stale"


def test_changes_between_latest_and_previous():
    rows = [
        _obs("old", 30, severity="low", issues=["possible leak"]),
        _obs("new", 2, severity="high", status="needs_review", issues=["visible lesions"], action="Inspect row 4"),
    ]
    summary = field_condition_summary(rows, field_id="f1", now=NOW)
    assert summary["latest"]["observation_id"] == "new"  # sorted newest first regardless of input order
    assert summary["latest"]["freshness"] == "fresh"
    kinds = {change["kind"]: change for change in summary["changes"]}
    assert kinds["severity_increased"] == {"kind": "severity_increased", "from": "low", "to": "high"}
    assert kinds["new_visible_issue"]["issues"] == ["visible lesions"]
    assert kinds["issue_not_seen_again"]["issues"] == ["possible leak"]
    assert summary["open_reviews"] == 1
    assert summary["next_action"] == "Inspect row 4"


def test_detection_change_requires_non_overlapping_bounds():
    overlapping = field_condition_summary([
        _obs("a", 50, totals=[{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 40}]),
        _obs("b", 1, totals=[{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}]),
    ], now=NOW)
    assert not [change for change in overlapping["changes"] if change["kind"] == "detection_count_changed"]
    separated = field_condition_summary([
        _obs("a", 50, totals=[{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 20}]),
        _obs("b", 1, totals=[{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}]),
    ], now=NOW)
    change = next(change for change in separated["changes"] if change["kind"] == "detection_count_changed")
    assert change["previous_bounds"] == [10, 20] and change["latest_bounds"] == [30, 60]


def test_conflicting_recent_assessments_are_flagged_not_replaced():
    rows = [_obs("a", 20, condition="damaged", issues=["x"]), _obs("b", 1, condition="healthy", issues=["x"])]
    change = next(change for change in field_condition_summary(rows, now=NOW)["changes"] if change["kind"] == "conflicting_recent_assessments")
    assert change["previous"] == "damaged" and change["latest"] == "healthy"
    far_apart = [_obs("a", 200, condition="damaged", issues=["x"]), _obs("b", 1, condition="healthy", issues=["x"])]
    assert not [c for c in field_condition_summary(far_apart, now=NOW)["changes"] if c["kind"] == "conflicting_recent_assessments"]


def test_stale_evidence_and_default_next_action():
    summary = field_condition_summary([_obs("a", 24 * 20, status="needs_review")], now=NOW)
    assert summary["latest"]["freshness"] == "stale"
    assert any(change["kind"] == "stale_evidence" for change in summary["changes"])
    assert summary["next_action"].startswith("Review the latest observation")


def test_deleted_observations_are_ignored():
    summary = field_condition_summary([_obs("a", 1, status="deleted"), _obs("b", 5)], now=NOW)
    assert summary["observations_considered"] == 1 and summary["latest"]["observation_id"] == "b"

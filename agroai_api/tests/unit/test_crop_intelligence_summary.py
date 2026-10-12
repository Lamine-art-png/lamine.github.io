from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.crop_intelligence import field_condition_summary, freshness

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _obs(obs_id, hours_ago, *, severity="low", status="completed", issues=(), condition=None, totals=None, action=None,
         block="Block 1", per_asset=None, plan=None, event_type=None, assets=None, vision_state="structured"):
    structured = {}
    if issues or condition:
        structured["vision"] = {"possible_issues": list(issues), "crop_condition": condition, "analysis_state": vision_state,
                                "confidence": None, "confidence_kind": "model_self_reported_uncalibrated"}
    if totals is not None:
        structured["detections"] = {"counts": {"totals": totals, "per_asset": per_asset or []}}
        if plan is not None:
            structured["detections"]["sampling_plan"] = plan
    return {
        "block_name": block, "event_type": event_type, "assets": list(assets or []),
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


PLAN = {"plan_id": "plan-1", "unit_ids": ["tree-4", "tree-9"]}


def test_changes_between_latest_and_previous():
    rows = [
        _obs("old", 30, severity="low", issues=["possible leak"], totals=[], plan=PLAN),
        _obs("new", 2, severity="high", status="needs_review", issues=["visible lesions"], action="Inspect row 4",
             totals=[], plan=PLAN),
    ]
    summary = field_condition_summary(rows, field_id="f1", now=NOW)
    assert summary["latest"]["observation_id"] == "new"  # sorted newest first regardless of input order
    assert summary["latest"]["freshness"] == "fresh"
    kinds = {change["kind"]: change for change in summary["changes"]}
    assert kinds["severity_increased"] == {"kind": "severity_increased", "from": "low", "to": "high", "trend": True,
                                           "basis": "same_sampling_units", "scope": "same_block_same_method"}
    assert summary["comparison"] == {"basis": "same_block_same_method", "previous_observation_id": "old",
                                     "block_key": "name:block 1", "method": "visual",
                                     "previous_observed_at": (NOW - timedelta(hours=30)).isoformat(), "gap_hours": 28.0,
                                     "spatial_coverage": "same_sampling_units"}
    assert kinds["new_visible_issue"]["issues"] == ["visible lesions"]
    assert kinds["issue_not_seen_again"]["issues"] == ["possible leak"]
    assert summary["open_reviews"] == 1
    assert summary["next_action"] == "Inspect row 4"


def test_detection_change_requires_non_overlapping_bounds():
    overlapping = field_condition_summary([
        _obs("a", 50, totals=[{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 40}]),
        _obs("b", 1, totals=[{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}]),
    ], now=NOW)
    assert not [change for change in overlapping["changes"] if change["kind"] in {"detection_count_changed", "different_observation_count"}]
    plan = {"plan_id": "plan-1", "unit_ids": ["tree-4", "tree-9"]}
    separated = field_condition_summary([
        _obs("a", 50, totals=[{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 20}], plan=plan),
        _obs("b", 1, totals=[{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}], plan=plan),
    ], now=NOW)
    change = next(change for change in separated["changes"] if change["kind"] == "detection_count_changed")
    assert change["previous_bounds"] == [10, 20] and change["latest_bounds"] == [30, 60]
    assert change["trend"] is True and change["basis"] == "same_sampling_units"


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



# ---------------------------------------------------------------------------
# Comparable scope (audit finding 4)
# ---------------------------------------------------------------------------

def test_different_blocks_are_not_compared_as_a_trend():
    rows = [
        _obs("a", 20, severity="high", condition="damaged", issues=["x"], block="Block 1"),
        _obs("b", 1, severity="low", condition="healthy", issues=["x"], block="Block 9"),
    ]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["comparison"] == {"basis": "no_comparable_prior",
                                     "reason": "no_prior_assessment_of_this_block_by_this_method_in_window",
                                     "window_records": 2}
    assert summary["changes"] == []
    blocks = {block["block_key"]: block for block in summary["field_snapshot"]["blocks"]}
    assert set(blocks) == {"name:block 1", "name:block 9"}
    assert "not a trend" in summary["field_snapshot"]["note"]


def test_comparison_uses_the_most_recent_same_block_same_method_observation():
    rows = [
        _obs("b9-old", 40, severity="low", condition="healthy", issues=["x"], block="Block 9"),
        _obs("b1", 20, severity="critical", condition="damaged", issues=["y"], block="Block 1"),
        _obs("b9-new", 2, severity="medium", condition="stressed", issues=["x"], block="block  9"),
    ]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["comparison"]["previous_observation_id"] == "b9-old"
    kinds = {change["kind"] for change in summary["changes"]}
    # No shared sample units: the severity difference and the disagreement are not a trend.
    assert kinds == {"severity_differs", "conflicting_recent_assessments"}
    differs = next(change for change in summary["changes"] if change["kind"] == "severity_differs")
    assert differs["trend"] is False and differs["reason"] == "spatial_coverage_not_established"
    conflict = next(change for change in summary["changes"] if change["kind"] == "conflicting_recent_assessments")
    assert conflict["spatial_coverage"] == "not_established" and "different parts of the block" in conflict["note"]
    assert all(change["scope"] == "same_block_same_method" for change in summary["changes"])


def test_visual_and_report_observations_are_not_compared():
    rows = [_obs("report", 10, severity="high"), _obs("visual", 1, severity="low", issues=["x"])]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["latest"]["method"] == "visual"
    assert summary["comparison"]["basis"] == "no_comparable_prior" and summary["changes"] == []


def test_count_change_requires_matching_coverage():
    def asset(frames, method="max_single_frame_lower_bound"):
        return [{"counts": {"cluster": {"count_method": method, "frames_considered": frames}}}]

    before = [{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 20}]
    after = [{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}]
    different = field_condition_summary([
        _obs("a", 50, totals=before, per_asset=asset(3)), _obs("b", 1, totals=after, per_asset=asset(6)),
    ], now=NOW)
    assert not [c for c in different["changes"] if c["kind"] == "detection_count_changed"]
    assert [(c["kind"], c["reason"]) for c in different["changes"]] == [("different_observation_count", "count_method_or_frames_differ")]
    plan = {"plan_id": "plan-1", "unit_ids": ["tree-4", "tree-9"]}
    same = field_condition_summary([
        _obs("a", 50, totals=before, per_asset=asset(3), plan=plan), _obs("b", 1, totals=after, per_asset=asset(3), plan=plan),
    ], now=NOW)
    assert [c["kind"] for c in same["changes"]] == ["detection_count_changed"]


def test_same_frames_in_different_places_are_not_a_trend():
    """Second review: two walks through different rows can have identical frame counts."""
    def asset(frames=3):
        return [{"counts": {"cluster": {"count_method": "max_single_frame_lower_bound", "frames_considered": frames}}}]

    before = [{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 20}]
    after = [{"label": "cluster", "observed_lower_bound": 30, "sum_upper_bound": 60}]
    cases = {
        "no_plan": (None, None),
        "different_units": ({"plan_id": "plan-1", "unit_ids": ["row-2"]}, {"plan_id": "plan-1", "unit_ids": ["row-7"]}),
        "different_plan": ({"plan_id": "plan-1", "unit_ids": ["row-2"]}, {"plan_id": "plan-2", "unit_ids": ["row-2"]}),
        "one_side_only": ({"plan_id": "plan-1", "unit_ids": ["row-2"]}, None),
    }
    for name, (plan_before, plan_after) in cases.items():
        summary = field_condition_summary([
            _obs("a", 50, totals=before, per_asset=asset(), plan=plan_before),
            _obs("b", 1, totals=after, per_asset=asset(), plan=plan_after),
        ], now=NOW)
        kinds = [(c["kind"], c.get("reason"), c.get("trend")) for c in summary["changes"]]
        assert kinds == [("different_observation_count", "spatial_coverage_not_established", False)], name


def test_unit_order_does_not_matter_for_the_same_sampling_units():
    def asset():
        return [{"counts": {"cluster": {"count_method": "tracked_unique", "frames_considered": 12}}}]

    summary = field_condition_summary([
        _obs("a", 50, totals=[{"label": "cluster", "observed_lower_bound": 10, "sum_upper_bound": 12}], per_asset=asset(),
             plan={"plan_id": "p", "unit_ids": ["t2", "t1"]}),
        _obs("b", 1, totals=[{"label": "cluster", "observed_lower_bound": 20, "sum_upper_bound": 22}], per_asset=asset(),
             plan={"plan_id": "p", "unit_ids": ["t1", "t2", "t1"]}),
    ], now=NOW)
    assert [c["kind"] for c in summary["changes"]] == ["detection_count_changed"]


def test_future_dated_records_are_excluded_not_fresh():
    rows = [_obs("past", 5, severity="low"), _obs("future", -72, severity="critical")]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["latest"]["observation_id"] == "past"
    assert summary["excluded"][0]["observation_id"] == "future"
    assert any(change["kind"] == "future_dated_records_excluded" for change in summary["changes"])
    assert summary["observations_considered"] == 1
    assert freshness(-24) == "future_dated"


def test_small_clock_skew_is_tolerated():
    summary = field_condition_summary([_obs("skew", -0.05)], now=NOW)  # three minutes ahead
    assert summary["latest"]["observation_id"] == "skew" and summary["latest"]["freshness"] == "fresh"


def test_only_future_records_gives_no_observations():
    summary = field_condition_summary([_obs("future", -10)], now=NOW)
    assert summary["status"] == "no_observations" and len(summary["excluded"]) == 1


# ---------------------------------------------------------------------------
# Review hardening: what may be compared, and with what claim
# ---------------------------------------------------------------------------

def test_observations_without_a_block_are_never_paired():
    rows = [_obs("a", 30, severity="low", issues=["x"], block=None), _obs("b", 2, severity="high", issues=["y"], block=None)]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["comparison"] == {"basis": "no_comparable_prior", "reason": "observation_has_no_block"}
    assert summary["changes"] == []
    assert summary["latest"]["block_key"] == "__field__"


def test_issue_differences_without_shared_sample_units_are_not_trends():
    rows = [_obs("a", 30, issues=["possible leak"]), _obs("b", 2, issues=["visible lesions"])]
    changes = {change["kind"]: change for change in field_condition_summary(rows, now=NOW)["changes"]}
    assert set(changes) == {"issue_seen_only_in_latest", "issue_seen_only_in_previous"}
    assert all(change["trend"] is False for change in changes.values())
    assert changes["issue_seen_only_in_latest"]["issues"] == ["visible lesions"]
    assert "confirm in the field" in changes["issue_seen_only_in_previous"]["note"]


def test_non_crop_records_are_neither_latest_nor_prior():
    rows = [
        _obs("crop-old", 40, severity="low", issues=["x"]),
        _obs("meter", 20, severity="critical", event_type="meter_reading"),
        _obs("crop-new", 10, severity="medium", issues=["x"]),
        _obs("irrigation", 1, severity="high", event_type="irrigation_event"),
    ]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["latest"]["observation_id"] == "crop-new"
    assert summary["comparison"]["previous_observation_id"] == "crop-old"
    assert [block["observation_id"] for block in summary["field_snapshot"]["blocks"]] == ["crop-new"]
    assert [entry["observation_id"] for entry in summary["timeline"]][0] == "irrigation"


def test_unfinished_records_are_neither_latest_nor_prior():
    rows = [
        _obs("done-old", 40, severity="low", issues=["x"]),
        _obs("failed", 20, severity="critical", status="failed", issues=["y"]),
        _obs("done-new", 10, severity="medium", issues=["x"]),
        _obs("processing", 1, status="processing"),
    ]
    summary = field_condition_summary(rows, now=NOW)
    assert summary["latest"]["observation_id"] == "done-new"
    assert summary["comparison"]["previous_observation_id"] == "done-old"
    assert summary["pending_processing"] == 2


def test_only_unfinished_or_non_crop_records_give_no_comparison():
    summary = field_condition_summary([_obs("p", 1, status="processing"), _obs("m", 5, event_type="meter_reading")], now=NOW)
    assert summary["status"] == "ok"
    assert summary["comparison"] == {"basis": "no_comparable_prior", "reason": "no_completed_crop_assessment"}
    assert summary["changes"] == []


def test_unanalysed_visual_media_is_not_compared_with_a_report():
    photo = [{"kind": "photo", "status": "stored"}]
    report = _obs("report", 30, severity="low")
    degraded = _obs("degraded", 2, severity="high", issues=["x"], vision_state="degraded")
    no_vision = _obs("photo-only", 1, severity="high", assets=photo)
    for latest in (degraded, no_vision):
        summary = field_condition_summary([report, latest], now=NOW)
        assert summary["latest"]["method"] == "visual_unassessed"
        assert summary["comparison"]["basis"] == "no_comparable_prior" and summary["changes"] == []
    deleted_photo = _obs("deleted-photo", 1, severity="high", assets=[{"kind": "photo", "status": "deleted"}])
    assert field_condition_summary([report, deleted_photo], now=NOW)["latest"]["method"] == "report"


def test_severity_is_normalized_and_unknown_values_are_not_ranked():
    rows = [_obs("a", 30, severity="low", totals=[], plan=PLAN), _obs("b", 2, severity=" HIGH ", totals=[], plan=PLAN)]
    change = field_condition_summary(rows, now=NOW)["changes"][0]
    assert (change["kind"], change["from"], change["to"]) == ("severity_increased", "low", "high")
    unknown = field_condition_summary([_obs("a", 30, severity="low"), _obs("b", 2, severity="urgent")], now=NOW)
    assert not [c for c in unknown["changes"] if c["kind"].startswith("severity")]
    assert unknown["latest"]["severity"] == "unrecognized"


def test_malformed_structured_data_does_not_break_the_summary():
    """PATCH can store any JSON in structured; the summary must not 500 on it."""
    malformed = [
        {"vision": {"possible_issues": "leak", "crop_condition": {"x": 1}, "safety_flags": 7, "analysis_state": "structured"}},
        {"vision": "not-an-object", "detections": {"counts": {"totals": "x", "per_asset": "y"}}},
        {"detections": {"counts": {"totals": [{"label": "cluster", "observed_lower_bound": "ten", "sum_upper_bound": None},
                                              "row"],
                                   "per_asset": [7, {"counts": {"cluster": "z"}}, {"counts": [1]}]},
                        "sampling_plan": {"plan_id": 5, "unit_ids": "tree-1"}}},
        {"detections": {"counts": {"totals": [{"label": ["cluster"]}],
                                   "per_asset": [{"counts": {"cluster": {"frames_considered": "3"}}}]}}},
    ]
    for structured in malformed:
        before = _obs("a", 30, issues=["x"], totals=[{"label": "cluster", "observed_lower_bound": 1, "sum_upper_bound": 2}])
        after = {**_obs("b", 2, issues=["x"]), "structured": structured, "task_ids": "t-1", "severity": 3}
        summary = field_condition_summary([before, after], now=NOW)
        assert summary["status"] == "ok", structured
        assert summary["latest"]["observation_id"] == "b"


def test_future_dated_total_counts_records_the_caller_did_not_fetch():
    summary = field_condition_summary([_obs("past", 5), _obs("future", -72)], now=NOW, future_dated_total=40)
    excluded = next(change for change in summary["changes"] if change["kind"] == "future_dated_records_excluded")
    assert excluded["count"] == 40 and summary["future_dated_excluded"] == 40
    assert len(summary["excluded"]) == 1


def test_vision_without_an_analysis_state_is_not_treated_as_structured():
    """Records from before the analysis contract include provider prose stored as vision."""
    structured = _obs("structured", 30, severity="medium", issues=["powdery mildew"])
    legacy = _obs("legacy", 2, severity="info", issues=["none"])
    del legacy["structured"]["vision"]["analysis_state"]
    summary = field_condition_summary([structured, legacy], now=NOW)
    assert summary["latest"]["method"] == "visual_unassessed"
    assert summary["latest"]["visual"]["analysis_state"] == "legacy_unverified"
    assert summary["comparison"]["basis"] == "no_comparable_prior" and summary["changes"] == []


def test_a_record_with_nothing_to_assess_does_not_replace_the_latest_assessment():
    """A voice note whose transcription was unavailable still finishes processing, but says nothing."""
    pest = _obs("pest", 24, severity="high", issues=["mites"])
    empty = {**_obs("empty-voice", 1, severity="info", status="needs_review"), "summary": "", "transcript": None,
             "structured": {}, "assets": [{"kind": "audio", "status": "stored"}]}
    summary = field_condition_summary([pest, empty], now=NOW)
    assert summary["latest"]["observation_id"] == "pest"
    assert summary["records_without_evidence"] == 1
    assert [block["observation_id"] for block in summary["field_snapshot"]["blocks"]] == ["pest"]
    assert summary["timeline"][0]["observation_id"] == "empty-voice"

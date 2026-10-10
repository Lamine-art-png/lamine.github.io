"""Evaluation harness tests.

The records built here are test inputs for the scorer's arithmetic and
refusal rules. They are not, and must never be reported as, model results.
"""
from __future__ import annotations

import json
import math

import pytest

from evals.field_vision import metrics
from evals.field_vision import validation_gate as gate


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------

def test_wilson_interval_matches_reference_values():
    low, high = metrics.Proportion(45, 50).wilson()
    assert low == pytest.approx(0.7864, abs=1e-4)
    assert high == pytest.approx(0.9565, abs=1e-4)
    assert metrics.Proportion(0, 0).wilson() is None
    assert metrics.Proportion(0, 0).value is None


def test_median_and_percentile():
    assert metrics.median([]) is None
    assert metrics.median([3, 1, 2]) == 2
    assert metrics.median([4, 1, 3, 2]) == 2.5
    assert metrics.percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    assert metrics.percentile([7], 50) == 7


def test_brier_and_ece():
    assert metrics.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert metrics.brier_score([0.5, 0.5], [1, 0]) == 0.25
    assert metrics.brier_score([], []) is None
    # Perfectly calibrated bins give zero ECE; overconfidence is penalized.
    assert metrics.expected_calibration_error([0.75] * 4, [1, 1, 1, 0]) == pytest.approx(0.0)
    assert metrics.expected_calibration_error([0.95] * 4, [1, 0, 1, 0]) == pytest.approx(0.45)


def test_iou():
    assert metrics.iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0
    assert metrics.iou([0, 0, 1, 1], [2, 2, 1, 1]) == 0.0
    assert metrics.iou([0, 0, 2, 2], [1, 1, 2, 2]) == pytest.approx(1 / 7)


def test_average_precision():
    truth = {"img1": [[0, 0, 10, 10]], "img2": [[0, 0, 10, 10]]}
    perfect = [("img1", 0.9, [0, 0, 10, 10]), ("img2", 0.8, [0, 0, 10, 10])]
    assert metrics.average_precision(perfect, truth) == pytest.approx(1.0)
    # A higher-scored false positive before the true positives lowers AP. The
    # precision envelope is 2/3 at both recall steps (0.5 and 1.0).
    with_fp = [("img1", 0.95, [50, 50, 5, 5]), *perfect]
    assert metrics.average_precision(with_fp, truth) == pytest.approx(2 / 3)
    # A duplicate detection of the same object is a false positive, not a second hit.
    duplicate = [("img1", 0.9, [0, 0, 10, 10]), ("img1", 0.85, [0, 0, 10, 10])]
    assert metrics.average_precision(duplicate, truth) == pytest.approx(0.5)
    assert metrics.average_precision(perfect, {}) is None


def test_count_errors_and_interval_coverage():
    errors = metrics.count_errors([10, 0, 5], [8, 0, 10])
    assert errors["mae"] == pytest.approx(7 / 3)
    assert errors["mape"] == pytest.approx((0.25 + 0.5) / 2)
    assert metrics.count_errors([], [])["mae"] is None
    assert metrics.interval_coverage([(1, 3), (5, 6)], [2, 7]) == 0.5


# ---------------------------------------------------------------------------
# #352 gate scorer
# ---------------------------------------------------------------------------

def _record(index: int, *, capture_type: str = "photo", split: str = "test", **overrides) -> dict:
    record = {
        "schema_version": gate.SCHEMA_VERSION,
        "observation_id": f"test-obs-{index}",
        "build_sha": "0" * 40,
        "split": split,
        "capture_type": capture_type,
        "device": "test-device",
        "crop": "test-crop",
        "lighting": "test-light",
        "media_quality": "clear",
        "consent": {"basis": "internal_staff_capture"},
        "grouping": {"grower": f"grower-{split}", "site": f"site-{split}", "season": "test", "device_group": f"dev-{split}"},
        "reviewer": {"id": "reviewer-test", "qualification": "agronomist"},
        "reference": {"visible_facts": [], "issues": [], "evidence_insufficient": False},
        "model": {"visible_facts": [{"label": "fact", "judgment": "correct"}], "severity": "low", "human_review_required": True},
        "flags": {},
        "recommendation_review": {"useful": True, "safe": True},
        "latency": {"first_live_result_ms": 8000, "durable_result_ms": 45000, "stable_connection": True},
    }
    for key, value in overrides.items():
        record[key] = value
    return record


def _full_test_split(**overrides) -> list[dict]:
    rows = []
    index = 0
    for capture_type, count in gate.REQUIRED_COMPOSITION.items():
        for _ in range(count):
            rows.append(_record(index, capture_type=capture_type, **overrides))
            index += 1
    return rows


def test_no_records_is_not_measured_and_fails():
    report = gate.evaluate([])
    assert not report.gate_passed
    assert report.composition["status"] == gate.NOT_MEASURED
    assert all(metric["status"] == gate.NOT_MEASURED for metric in report.metrics.values())


def test_small_sample_reports_insufficient_not_a_score():
    report = gate.evaluate([_record(i) for i in range(5)])
    assert report.metrics["visible_fact_precision"]["status"] == gate.INSUFFICIENT
    assert report.metrics["visible_fact_precision"]["value"] == 1.0  # shown, but not judged
    assert report.composition["status"] == gate.INSUFFICIENT
    assert report.composition["shortfall"]["walk_video"] == 20
    assert not report.gate_passed


def test_complete_clean_test_split_meets_every_target():
    report = gate.evaluate(_full_test_split())
    assert report.composition["status"] == gate.MEETS
    statuses = {key: metric["status"] for key, metric in report.metrics.items()}
    # No reference issues and no high/critical results in this input: those
    # properties are untested, so they are honestly unmeasured, not passed.
    assert statuses.pop("issue_recall") == gate.NOT_MEASURED
    assert statuses.pop("high_severity_human_confirmation") == gate.NOT_MEASURED
    assert set(statuses.values()) == {gate.MEETS}
    assert not report.gate_passed  # an unmeasured metric blocks the gate


def test_severe_false_positive_rate_definition():
    rows = _full_test_split()
    for row in rows[:5]:
        row["model"] = {**row["model"], "severity": "critical"}
    report = gate.evaluate(rows)
    metric = report.metrics["severe_false_positive_rate"]
    assert metric["numerator"] == 5 and metric["denominator"] == 50
    assert metric["value"] == pytest.approx(0.1)
    assert metric["status"] == gate.BELOW


def test_issue_recall_and_precision_use_reviewer_judgments():
    rows = _full_test_split()
    for index, row in enumerate(rows[:20]):
        row["reference"] = {**row["reference"], "issues": [{"category": "visible_stress", "severity": "medium", "detected_by_model": index % 4 != 0}]}
    for row in rows[:10]:
        row["model"] = {**row["model"], "visible_facts": [{"label": "fact", "judgment": "unsupported"}]}
    report = gate.evaluate(rows)
    assert report.metrics["issue_recall"]["value"] == pytest.approx(15 / 20)
    assert report.metrics["issue_recall"]["status"] == gate.BELOW
    assert report.metrics["visible_fact_precision"]["value"] == pytest.approx(40 / 50)
    assert report.metrics["visible_fact_precision"]["status"] == gate.BELOW


def test_poor_media_is_excluded_from_precision():
    rows = _full_test_split()
    for row in rows[:10]:
        row["media_quality"] = "poor"
        row["model"] = {**row["model"], "visible_facts": [{"label": "fact", "judgment": "incorrect"}]}
    metric = gate.evaluate(rows).metrics["visible_fact_precision"]
    assert metric["denominator"] == 40 and metric["value"] == 1.0


def test_measurement_claim_detected_from_model_text_even_without_reviewer_flag():
    rows = _full_test_split()
    rows[3]["model"] = {**rows[3]["model"], "recommendation": "Apply 2 L/ha of fungicide."}
    metric = gate.evaluate(rows).metrics["unsupported_measurement_claims"]
    assert metric["count"] == 1
    assert metric["status"] == gate.BELOW


def test_unconfirmed_high_severity_fails_confirmation_target():
    rows = _full_test_split()
    rows[0]["model"] = {**rows[0]["model"], "severity": "high", "human_review_required": False}
    metric = gate.evaluate(rows).metrics["high_severity_human_confirmation"]
    assert metric["value"] == 0.0 and metric["status"] == gate.BELOW


def test_latency_uses_only_stable_connections_for_live():
    rows = _full_test_split()
    for row in rows:
        row["latency"] = {"first_live_result_ms": 30000, "durable_result_ms": 120000, "stable_connection": False}
    report = gate.evaluate(rows)
    assert report.metrics["median_first_live_result_seconds"]["status"] == gate.NOT_MEASURED
    assert report.metrics["median_durable_result_seconds"]["value"] == 120.0
    assert report.metrics["median_durable_result_seconds"]["status"] == gate.BELOW


def test_split_leakage_is_reported_and_blocks_gate():
    rows = _full_test_split()
    leaked = _record(999, split="train")
    leaked["grouping"] = dict(rows[0]["grouping"])
    report = gate.evaluate([*rows, leaked])
    assert any("grower" in item for item in report.leakage)
    assert not report.gate_passed


def test_only_test_split_is_scored():
    rows = _full_test_split() + [_record(1000 + i, split="calibration", model={"visible_facts": [{"label": "x", "judgment": "incorrect"}], "severity": "critical", "human_review_required": True}) for i in range(30)]
    report = gate.evaluate(rows)
    assert report.composition["total"] == 50
    assert report.metrics["visible_fact_precision"]["value"] == 1.0


def test_record_validation_rejects_bad_records(tmp_path):
    good = _record(1)
    bad = _record(2, capture_type="drone", media_quality="great")
    bad["consent"] = {"basis": "assumed"}
    bad["model"] = {"visible_facts": [{"label": "fact"}], "severity": "catastrophic", "human_review_required": True}
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join([json.dumps(good), json.dumps(bad), "not json"]) + "\n", encoding="utf-8")
    records, errors = gate.load_records(path)
    assert len(records) == 2
    joined = "\n".join(errors)
    for expected in ("capture_type", "media_quality", "consent.basis", "model.severity", "judgment", "invalid JSON"):
        assert expected in joined
    assert not gate.evaluate(records, errors).gate_passed


def test_cli_writes_report_and_exit_code(tmp_path, capsys):
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in _full_test_split()) + "\n", encoding="utf-8")
    out = tmp_path / "report.json"
    code = gate.main([str(path), "--json", str(out)])
    assert code == 1  # issue recall is unmeasured, so the gate cannot pass
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["metrics"]["issue_recall"]["status"] == gate.NOT_MEASURED
    assert "Field Intelligence validation gate" in capsys.readouterr().out


def test_template_record_is_schema_valid():
    from pathlib import Path

    template = json.loads((Path(gate.__file__).with_name("record_template.json")).read_text(encoding="utf-8"))
    template.pop("_comment")
    assert gate.validate_record(template, 1) == []
    assert not math.isnan(gate.evaluate([template]).metrics["visible_fact_precision"]["value"])

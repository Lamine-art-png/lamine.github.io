"""Score the Field Intelligence 50-observation validation gate (issue #352).

Usage::

    python -m evals.field_vision.validation_gate reviewed.jsonl
    python -m evals.field_vision.validation_gate reviewed.jsonl --json report.json

Input is JSON Lines; each line is one reviewed observation following
``ANNOTATION_GUIDELINES.md`` (schema ``field-vision-ground-truth/1``). The
reviewer, not this script, decides whether each model visible fact is correct
and whether each reference issue was detected: string matching cannot judge
agronomic correctness.

Every metric reports its definition, numerator, denominator, Wilson 95%
interval, and one of these statuses:

- ``NOT MEASURED``: no eligible records.
- ``INSUFFICIENT SAMPLE``: fewer eligible records than the metric's minimum.
- ``MEETS TARGET`` or ``BELOW TARGET``: judged on the point estimate. The
  report also says whether the interval's lower bound meets the target,
  because 50 observations leave wide intervals.

The targets are the #352 release thresholds. They are verification targets,
not results.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.services.field_vision_safety import find_unsupported_measurements
from evals.field_vision.metrics import Proportion, median

SCHEMA_VERSION = "field-vision-ground-truth/1"
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
CAPTURE_TYPES = {"walk_video", "photo", "voice", "offline"}
MEDIA_QUALITY = {"clear", "usable", "poor"}
CONSENT_BASES = {"customer_written_consent", "internal_staff_capture", "licensed_dataset"}
SPLITS = {"train", "calibration", "test"}
REQUIRED_COMPOSITION = {"walk_video": 20, "photo": 15, "voice": 10, "offline": 5}
REQUIRED_TOTAL = 50

NOT_MEASURED = "NOT MEASURED"
INSUFFICIENT = "INSUFFICIENT SAMPLE"
MEETS = "MEETS TARGET"
BELOW = "BELOW TARGET"


@dataclass
class Target:
    key: str
    description: str
    definition: str
    comparator: str  # ">=" | "<=" | "==0"
    threshold: float
    minimum_n: int


TARGETS = [
    Target("visible_fact_precision", "Visible-fact precision on clear/usable evidence",
           "correct model visible facts / all model visible facts, on records with media_quality clear or usable",
           ">=", 0.90, 30),
    Target("issue_recall", "Issue/hypothesis recall on reviewer-confirmed visible issues",
           "reference issues the reviewer marked detected / all reference issues",
           ">=", 0.80, 15),
    Target("severe_false_positive_rate", "Severe false-positive rate",
           "records where the model said high/critical but the reference maximum is below high / records whose reference maximum is below high",
           "<=", 0.05, 20),
    Target("unsupported_measurement_claims", "Fabricated chemistry/residue/dosage/lab/soil/tissue claims",
           "records where the shared runtime detector finds a claim in model text, or the reviewer flags one",
           "==0", 0, 1),
    Target("unsupported_certainty", "Unsupported statements presented as confirmed diagnoses",
           "records the reviewer flagged for unsupported certainty",
           "==0", 0, 1),
    Target("useful_safe_recommendations", "Recommendations rated useful and safe",
           "records whose recommendation the reviewer rated both useful and safe / records with a reviewed recommendation",
           ">=", 0.85, 20),
    Target("high_severity_human_confirmation", "High/critical results requiring human confirmation",
           "high/critical model results with human_review_required true / all high/critical model results",
           ">=", 1.0, 1),
    Target("median_first_live_result_seconds", "Median first sampled live result on a stable connection",
           "median of latency.first_live_result_ms / 1000 over records with stable_connection true",
           "<=", 12.0, 10),
    Target("median_durable_result_seconds", "Median durable multimodal result after upload",
           "median of latency.durable_result_ms / 1000",
           "<=", 90.0, 10),
]


@dataclass
class ValidationReport:
    records: int
    errors: list[str] = field(default_factory=list)
    composition: dict[str, Any] = field(default_factory=dict)
    leakage: list[str] = field(default_factory=list)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    strata: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def gate_passed(self) -> bool:
        return (
            not self.errors
            and not self.leakage
            and self.composition.get("status") == MEETS
            and all(metric["status"] == MEETS for metric in self.metrics.values())
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "records": self.records,
            "gate_passed": self.gate_passed,
            "errors": self.errors,
            "composition": self.composition,
            "leakage": self.leakage,
            "metrics": self.metrics,
            "strata": self.strata,
        }


def _require(record: dict[str, Any], path: str, errors: list[str], line: int) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            errors.append(f"line {line}: missing {path}")
            return None
        value = value[part]
    return value


def validate_record(record: dict[str, Any], line: int) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"line {line}: schema_version must be {SCHEMA_VERSION}")
    for path in (
        "observation_id", "build_sha", "split", "capture_type", "media_quality", "device",
        "consent.basis", "grouping.grower", "grouping.site", "grouping.season",
        "reviewer.id", "reviewer.qualification", "reference.issues", "reference.evidence_insufficient",
        "model.visible_facts", "model.severity", "model.human_review_required",
    ):
        _require(record, path, errors, line)
    if record.get("capture_type") not in CAPTURE_TYPES:
        errors.append(f"line {line}: capture_type must be one of {sorted(CAPTURE_TYPES)}")
    if record.get("media_quality") not in MEDIA_QUALITY:
        errors.append(f"line {line}: media_quality must be one of {sorted(MEDIA_QUALITY)}")
    if record.get("split") not in SPLITS:
        errors.append(f"line {line}: split must be one of {sorted(SPLITS)}")
    if (record.get("consent") or {}).get("basis") not in CONSENT_BASES:
        errors.append(f"line {line}: consent.basis must be one of {sorted(CONSENT_BASES)}")
    if str((record.get("model") or {}).get("severity")) not in SEVERITY_RANK:
        errors.append(f"line {line}: model.severity is not a contract severity")
    for issue in (record.get("reference") or {}).get("issues") or []:
        if str(issue.get("severity")) not in SEVERITY_RANK or not isinstance(issue.get("detected_by_model"), bool):
            errors.append(f"line {line}: each reference issue needs a contract severity and detected_by_model")
            break
    for fact in (record.get("model") or {}).get("visible_facts") or []:
        if fact.get("judgment") not in {"correct", "incorrect", "unsupported"}:
            errors.append(f"line {line}: each model visible fact needs judgment correct|incorrect|unsupported")
            break
    return errors


def load_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number}: record must be an object")
            continue
        errors.extend(validate_record(record, line_number))
        records.append(record)
    return records, errors


def _model_text(record: dict[str, Any]) -> str:
    model = record.get("model") or {}
    parts: list[str] = [str(model.get("summary") or ""), str(model.get("recommendation") or "")]
    for key in ("visible_facts", "hypotheses"):
        for item in model.get(key) or []:
            parts.extend(str(item.get(part) or "") for part in ("label", "evidence", "verification"))
    return "\n".join(part for part in parts if part)


def _status(target: Target, value: float | None, n: int) -> str:
    if n == 0 or value is None:
        return NOT_MEASURED
    if n < target.minimum_n:
        return INSUFFICIENT
    if target.comparator == ">=":
        return MEETS if value >= target.threshold else BELOW
    if target.comparator == "<=":
        return MEETS if value <= target.threshold else BELOW
    return MEETS if value == 0 else BELOW


def _proportion_metric(target: Target, proportion: Proportion) -> dict[str, Any]:
    interval = proportion.wilson()
    value = proportion.value
    status = _status(target, value, proportion.total)
    bound_meets = None
    if interval is not None and status in {MEETS, BELOW}:
        bound_meets = interval[0] >= target.threshold if target.comparator == ">=" else interval[1] <= target.threshold
    return {
        "description": target.description,
        "definition": target.definition,
        "target": f"{target.comparator} {target.threshold}",
        "numerator": proportion.successes,
        "denominator": proportion.total,
        "value": round(value, 4) if value is not None else None,
        "wilson_95": [round(interval[0], 4), round(interval[1], 4)] if interval else None,
        "interval_bound_meets_target": bound_meets,
        "minimum_n": target.minimum_n,
        "status": status,
    }


def _count_metric(target: Target, count: int, n: int) -> dict[str, Any]:
    return {
        "description": target.description,
        "definition": target.definition,
        "target": "== 0",
        "count": count,
        "records_checked": n,
        "status": _status(target, float(count), n),
    }


def _median_metric(target: Target, seconds: list[float]) -> dict[str, Any]:
    value = median(seconds)
    return {
        "description": target.description,
        "definition": target.definition,
        "target": f"{target.comparator} {target.threshold}",
        "n": len(seconds),
        "value": round(value, 2) if value is not None else None,
        "minimum_n": target.minimum_n,
        "status": _status(target, value, len(seconds)),
    }


def compute_metrics(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = list(records)
    by_key = {target.key: target for target in TARGETS}

    fact_correct = fact_total = 0
    issues_detected = issues_total = 0
    negatives = false_positives = 0
    measurement_claims = certainty_flags = 0
    recommendations_ok = recommendations_reviewed = 0
    high_confirmed = high_total = 0
    live_seconds: list[float] = []
    durable_seconds: list[float] = []

    for record in rows:
        model = record.get("model") or {}
        reference = record.get("reference") or {}
        flags = record.get("flags") or {}
        if record.get("media_quality") in {"clear", "usable"}:
            for fact in model.get("visible_facts") or []:
                fact_total += 1
                fact_correct += fact.get("judgment") == "correct"
        for issue in reference.get("issues") or []:
            issues_total += 1
            issues_detected += bool(issue.get("detected_by_model"))
        reference_max = max((SEVERITY_RANK.get(str(issue.get("severity")), 0) for issue in reference.get("issues") or []), default=0)
        model_rank = SEVERITY_RANK.get(str(model.get("severity")), 0)
        if reference_max < SEVERITY_RANK["high"]:
            negatives += 1
            false_positives += model_rank >= SEVERITY_RANK["high"]
        if find_unsupported_measurements(_model_text(record)) or flags.get("chemical_numeric_claim"):
            measurement_claims += 1
        certainty_flags += bool(flags.get("unsupported_certainty"))
        review = record.get("recommendation_review")
        if isinstance(review, dict) and isinstance(review.get("useful"), bool) and isinstance(review.get("safe"), bool):
            recommendations_reviewed += 1
            recommendations_ok += review["useful"] and review["safe"]
        if model_rank >= SEVERITY_RANK["high"]:
            high_total += 1
            high_confirmed += model.get("human_review_required") is True
        latency = record.get("latency") or {}
        if isinstance(latency.get("first_live_result_ms"), (int, float)) and latency.get("stable_connection") is True:
            live_seconds.append(latency["first_live_result_ms"] / 1000)
        if isinstance(latency.get("durable_result_ms"), (int, float)):
            durable_seconds.append(latency["durable_result_ms"] / 1000)

    return {
        "visible_fact_precision": _proportion_metric(by_key["visible_fact_precision"], Proportion(fact_correct, fact_total)),
        "issue_recall": _proportion_metric(by_key["issue_recall"], Proportion(issues_detected, issues_total)),
        "severe_false_positive_rate": _proportion_metric(by_key["severe_false_positive_rate"], Proportion(false_positives, negatives)),
        "unsupported_measurement_claims": _count_metric(by_key["unsupported_measurement_claims"], measurement_claims, len(rows)),
        "unsupported_certainty": _count_metric(by_key["unsupported_certainty"], certainty_flags, len(rows)),
        "useful_safe_recommendations": _proportion_metric(by_key["useful_safe_recommendations"], Proportion(recommendations_ok, recommendations_reviewed)),
        "high_severity_human_confirmation": _proportion_metric(by_key["high_severity_human_confirmation"], Proportion(high_confirmed, high_total)),
        "median_first_live_result_seconds": _median_metric(by_key["median_first_live_result_seconds"], live_seconds),
        "median_durable_result_seconds": _median_metric(by_key["median_durable_result_seconds"], durable_seconds),
    }


def composition(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(record.get("capture_type")) for record in records)
    shortfall = {kind: needed - counts.get(kind, 0) for kind, needed in REQUIRED_COMPOSITION.items() if counts.get(kind, 0) < needed}
    meets = len(records) >= REQUIRED_TOTAL and not shortfall
    return {
        "total": len(records),
        "required_total": REQUIRED_TOTAL,
        "by_capture_type": dict(sorted(counts.items())),
        "required_by_capture_type": REQUIRED_COMPOSITION,
        "shortfall": shortfall,
        "status": NOT_MEASURED if not records else (MEETS if meets else INSUFFICIENT),
    }


def leakage(records: list[dict[str, Any]]) -> list[str]:
    """Flag any grower, site, or device group present in more than one split.

    Train/calibration/test must be separated by grower, site, season and
    device so scores are not inflated by near-duplicate evidence.
    """
    problems: list[str] = []
    for key in ("grower", "site", "device_group"):
        splits: dict[str, set[str]] = defaultdict(set)
        for record in records:
            group = (record.get("grouping") or {}).get(key)
            if group:
                splits[str(group)].add(str(record.get("split")))
        for group, seen in sorted(splits.items()):
            if len(seen) > 1:
                problems.append(f"{key} {group!r} appears in splits {sorted(seen)}")
    return problems


def evaluate(records: list[dict[str, Any]], errors: list[str] | None = None) -> ValidationReport:
    report = ValidationReport(records=len(records), errors=list(errors or []))
    report.leakage = leakage(records)
    test_records = [record for record in records if record.get("split") == "test"]
    report.composition = composition(test_records)
    report.metrics = compute_metrics(test_records)
    for stratum in ("crop", "capture_type", "media_quality", "lighting", "device"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in test_records:
            groups[str(record.get(stratum) or "unspecified")].append(record)
        report.strata[stratum] = {}
        for name, rows in sorted(groups.items()):
            metrics = compute_metrics(rows)
            report.strata[stratum][name] = {
                "records": len(rows),
                "visible_fact_precision": metrics["visible_fact_precision"],
                "issue_recall": metrics["issue_recall"],
            }
    return report


def render_markdown(report: ValidationReport) -> str:
    lines = [
        "# Field Intelligence validation gate (#352)",
        "",
        f"- Records: {report.records} (test split: {report.composition.get('total', 0)})",
        f"- Gate passed: **{'YES' if report.gate_passed else 'NO'}**",
        f"- Composition: {report.composition.get('status')} {report.composition.get('by_capture_type')}",
    ]
    if report.composition.get("shortfall"):
        lines.append(f"- Composition shortfall: {report.composition['shortfall']}")
    if report.errors:
        lines.append(f"- Validation errors: {len(report.errors)} (first: {report.errors[0]})")
    if report.leakage:
        lines.append(f"- Split leakage: {report.leakage}")
    lines += ["", "| Metric | Target | Value | 95% interval | n | Status |", "|---|---|---|---|---|---|"]
    for metric in report.metrics.values():
        value = metric.get("value", metric.get("count"))
        n = metric.get("denominator", metric.get("n", metric.get("records_checked")))
        interval = metric.get("wilson_95")
        lines.append(
            f"| {metric['description']} | {metric['target']} | {'—' if value is None else value} | "
            f"{'—' if not interval else f'{interval[0]}–{interval[1]}'} | {n} | {metric['status']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("records", type=Path, help="reviewed observations, JSON Lines")
    parser.add_argument("--json", type=Path, help="write the full report as JSON")
    args = parser.parse_args(argv)
    records, errors = load_records(args.records)
    report = evaluate(records, errors)
    if args.json:
        args.json.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    sys.stdout.write(render_markdown(report))
    return 0 if report.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

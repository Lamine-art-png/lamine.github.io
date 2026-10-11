"""Evaluate a crop object detector on held-out, consented ground truth.

Usage::

    python -m evals.field_vision.detection_eval ground_truth.json predictions.json \\
        --crop almond --model-id rtdetr-almond --model-version 1.0 --json report.json

Ground truth (COCO-like, boxes in pixels ``[x, y, w, h]``)::

    {"images": [{"id": "img-1", "width": 1280, "height": 960, "split": "test",
                 "consent": {"basis": "customer_written_consent"},
                 "grouping": {"grower": "g1", "site": "s1", "season": "2026", "device_group": "ios"}}],
     "annotations": [{"image_id": "img-1", "label": "nut", "bbox": [10, 20, 30, 30]}]}

Predictions: ``[{"image_id": "img-1", "label": "nut", "bbox": [...], "score": 0.83}]``.

The report gives, per label and on the test split only: AP at IoU 0.50,
AP averaged over IoU 0.50:0.95, recall, count MAE/MAPE at a score
threshold, and score calibration (ECE, Brier) of detections matched at IoU
0.50. It refuses to score when images lack consent, when growers, sites or
devices leak across splits, or when the test split is too small, and says
NOT MEASURED or INSUFFICIENT SAMPLE instead of producing a number.

A passing report is evidence for a reviewer; registering a detector in
``app/services/crop_model_registry.py`` remains a code-reviewed decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.crop_profiles import get_profile
from evals.field_vision.metrics import average_precision, brier_score, count_errors, expected_calibration_error, iou

REPORT_VERSION = "detection-eval/1"
CONSENT_BASES = {"customer_written_consent", "internal_staff_capture", "licensed_dataset"}
IOU_THRESHOLDS = [round(0.5 + 0.05 * step, 2) for step in range(10)]
MIN_TEST_IMAGES = 50
MIN_TEST_GROWERS = 3
NOT_MEASURED = "NOT MEASURED"
INSUFFICIENT = "INSUFFICIENT SAMPLE"
MEASURED = "MEASURED"


@dataclass
class DetectionReport:
    crop_id: str
    model_id: str | None
    model_version: str | None
    status: str
    errors: list[str] = field(default_factory=list)
    leakage: list[str] = field(default_factory=list)
    test_images: int = 0
    test_growers: int = 0
    labels: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": REPORT_VERSION, "crop_id": self.crop_id, "model_id": self.model_id,
            "model_version": self.model_version, "status": self.status, "errors": self.errors,
            "leakage": self.leakage, "test_images": self.test_images, "test_growers": self.test_growers,
            "minimums": {"test_images": MIN_TEST_IMAGES, "test_growers": MIN_TEST_GROWERS},
            "labels": self.labels,
            "note": "Evidence for review only. Registration in crop_model_registry is a code-reviewed decision.",
        }


def _normalized(box: Any, width: Any, height: Any) -> list[float] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not width or not height:
        return None
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return [x / width, y / height, w / width, h / height]


def _leakage(images: list[dict[str, Any]]) -> list[str]:
    problems = []
    for key in ("grower", "site", "device_group"):
        splits: dict[str, set[str]] = defaultdict(set)
        for image in images:
            group = (image.get("grouping") or {}).get(key)
            if group:
                splits[str(group)].add(str(image.get("split")))
        problems.extend(f"{key} {group!r} appears in splits {sorted(seen)}" for group, seen in sorted(splits.items()) if len(seen) > 1)
    return problems


def _matches(predictions: list[tuple[str, float, list[float]]], truth: dict[str, list[list[float]]], threshold: float) -> list[int]:
    """Greedy score-ordered matching; returns 1 for a true positive, else 0, in score order."""
    used = {image: [False] * len(boxes) for image, boxes in truth.items()}
    outcomes = []
    for image_id, _score, box in sorted(predictions, key=lambda item: -item[1]):
        best, best_index = 0.0, -1
        for index, candidate in enumerate(truth.get(image_id, [])):
            overlap = iou(box, candidate)
            if overlap > best:
                best, best_index = overlap, index
        if best >= threshold and best_index >= 0 and not used[image_id][best_index]:
            used[image_id][best_index] = True
            outcomes.append(1)
        else:
            outcomes.append(0)
    return outcomes


def evaluate(
    ground_truth: dict[str, Any], predictions: list[dict[str, Any]], *, crop_id: str,
    model_id: str | None = None, model_version: str | None = None, score_threshold: float = 0.5,
) -> DetectionReport:
    profile = get_profile(crop_id)
    report = DetectionReport(crop_id=crop_id, model_id=model_id, model_version=model_version, status=NOT_MEASURED)
    if profile is None:
        report.errors.append(f"unknown crop profile {crop_id!r}")
        return report
    images = [image for image in ground_truth.get("images") or [] if isinstance(image, dict)]
    by_id = {str(image.get("id")): image for image in images}
    for image in images:
        if (image.get("consent") or {}).get("basis") not in CONSENT_BASES:
            report.errors.append(f"image {image.get('id')!r} has no accepted consent basis")
        if image.get("split") not in {"train", "calibration", "test"}:
            report.errors.append(f"image {image.get('id')!r} has no train/calibration/test split")
    report.leakage = _leakage(images)
    allowed = set(profile.detection_labels)
    test_ids = {image_id for image_id, image in by_id.items() if image.get("split") == "test"}
    report.test_images = len(test_ids)
    report.test_growers = len({(by_id[i].get("grouping") or {}).get("grower") for i in test_ids} - {None})

    truth: dict[str, dict[str, list[list[float]]]] = defaultdict(lambda: defaultdict(list))
    for annotation in ground_truth.get("annotations") or []:
        image = by_id.get(str(annotation.get("image_id")))
        label = str(annotation.get("label") or "")
        if image is None or str(annotation.get("image_id")) not in test_ids:
            continue
        if label not in allowed:
            report.errors.append(f"ground-truth label {label!r} is not in the {crop_id} profile")
            continue
        box = _normalized(annotation.get("bbox"), image.get("width"), image.get("height"))
        if box is None:
            report.errors.append(f"invalid ground-truth box on image {annotation.get('image_id')!r}")
            continue
        truth[label][str(annotation["image_id"])].append(box)

    predicted: dict[str, list[tuple[str, float, list[float]]]] = defaultdict(list)
    for prediction in predictions:
        image_id = str(prediction.get("image_id"))
        if image_id not in test_ids:
            continue
        label = str(prediction.get("label") or "")
        score = prediction.get("score")
        box = _normalized(prediction.get("bbox"), by_id[image_id].get("width"), by_id[image_id].get("height"))
        if label not in allowed or box is None or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
            report.errors.append(f"invalid prediction on image {image_id!r}")
            continue
        predicted[label].append((image_id, float(score), box))

    if report.errors or report.leakage:
        report.status = NOT_MEASURED
        report.errors = report.errors[:50]
        return report
    if not test_ids or not any(truth.values()):
        return report
    sufficient = report.test_images >= MIN_TEST_IMAGES and report.test_growers >= MIN_TEST_GROWERS

    for label in sorted(set(truth) | set(predicted)):
        label_truth = {image_id: boxes for image_id, boxes in truth.get(label, {}).items()}
        label_predictions = predicted.get(label, [])
        ap50 = average_precision(label_predictions, label_truth, 0.5)
        ap_values = [average_precision(label_predictions, label_truth, threshold) for threshold in IOU_THRESHOLDS]
        outcomes = _matches(label_predictions, label_truth, 0.5)
        scores = [score for _, score, _ in sorted(label_predictions, key=lambda item: -item[1])]
        total_truth = sum(len(boxes) for boxes in label_truth.values())
        predicted_counts = [sum(1 for image, score, _ in label_predictions if image == image_id and score >= score_threshold)
                            for image_id in sorted(test_ids)]
        true_counts = [len(label_truth.get(image_id, [])) for image_id in sorted(test_ids)]
        counts = count_errors(predicted_counts, true_counts)
        report.labels[label] = {
            "ground_truth_objects": total_truth,
            "predictions": len(label_predictions),
            "ap50": None if ap50 is None else round(ap50, 4),
            "ap50_95": None if any(value is None for value in ap_values) else round(sum(ap_values) / len(ap_values), 4),
            "recall50": round(sum(outcomes) / total_truth, 4) if total_truth else None,
            "count_mae": None if counts["mae"] is None else round(counts["mae"], 3),
            "count_mape": None if counts["mape"] is None else round(counts["mape"], 4),
            "count_score_threshold": score_threshold,
            "score_ece": None if not scores else round(expected_calibration_error(scores, outcomes), 4),
            "score_brier": None if not scores else round(brier_score(scores, outcomes), 4),
        }
    report.status = MEASURED if sufficient else INSUFFICIENT
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a crop detector on held-out ground truth")
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--crop", required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--model-version")
    parser.add_argument("--score-threshold", type=float, default=0.5)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = evaluate(
        json.loads(args.ground_truth.read_text(encoding="utf-8")),
        json.loads(args.predictions.read_text(encoding="utf-8")),
        crop_id=args.crop, model_id=args.model_id, model_version=args.model_version, score_threshold=args.score_threshold,
    ).to_dict()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0 if report["status"] == MEASURED else 1


if __name__ == "__main__":
    raise SystemExit(main())

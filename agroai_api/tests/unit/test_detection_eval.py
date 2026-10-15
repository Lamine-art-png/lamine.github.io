"""Detector evaluation harness. Inputs are constructed test fixtures, not results."""
from __future__ import annotations

import json

import pytest

from evals.field_vision import detection_eval as de


def _image(index, *, split="test", grower=None):
    return {
        "id": f"img-{index}", "width": 1000, "height": 1000, "split": split,
        "consent": {"basis": "internal_staff_capture"},
        "grouping": {"grower": grower or f"grower-{split}-{index % 3}", "site": f"site-{split}-{index % 3}",
                     "season": "2026", "device_group": f"dev-{split}"},
    }


def _dataset(n_images=60, nuts_per_image=4):
    images = [_image(i) for i in range(n_images)]
    annotations = [
        {"image_id": image["id"], "label": "nut", "bbox": [100 * k, 100, 50, 50]}
        for image in images for k in range(1, nuts_per_image + 1)
    ]
    return {"images": images, "annotations": annotations}


def _perfect_predictions(dataset, score=0.9):
    return [{"image_id": a["image_id"], "label": a["label"], "bbox": a["bbox"], "score": score} for a in dataset["annotations"]]


def test_perfect_detector_measures_ap_one_and_zero_count_error():
    data = _dataset()
    report = de.evaluate(data, _perfect_predictions(data), crop_id="almond", model_id="m", model_version="1")
    assert report.status == de.MEASURED
    nut = report.labels["nut"]
    assert nut["ap50"] == 1.0 and nut["ap50_95"] == 1.0 and nut["recall50"] == 1.0
    assert nut["count_mae"] == 0.0 and nut["count_mape"] == 0.0


def test_shifted_boxes_lower_strict_iou_ap_but_not_ap50():
    data = _dataset()
    shifted = [{**p, "bbox": [p["bbox"][0] + 10, p["bbox"][1], 50, 50]} for p in _perfect_predictions(data)]
    nut = de.evaluate(data, shifted, crop_id="almond").labels["nut"]
    # IoU of a 50px box shifted by 10px: 40*50 / (2*2500 - 2000) = 2/3 -> TP up to IoU 0.65, missed above.
    assert nut["ap50"] == 1.0
    assert nut["ap50_95"] == pytest.approx(0.4)  # thresholds 0.50..0.65 hit (4 of 10)


def test_missed_and_spurious_detections_affect_recall_and_counts():
    data = _dataset()
    predictions = [p for i, p in enumerate(_perfect_predictions(data)) if i % 4 != 0]  # drop 1 of 4 per image
    predictions += [{"image_id": "img-0", "label": "nut", "bbox": [900, 900, 50, 50], "score": 0.95}]
    nut = de.evaluate(data, predictions, crop_id="almond").labels["nut"]
    assert nut["recall50"] == pytest.approx(0.75)
    assert nut["count_mae"] == pytest.approx((59 * 1 + 0) / 60, abs=1e-3)  # img-0: 3 found + 1 spurious = 4
    assert nut["ap50"] < 1.0


def test_low_scores_are_excluded_from_counts():
    data = _dataset()
    nut = de.evaluate(data, _perfect_predictions(data, score=0.3), crop_id="almond", score_threshold=0.5).labels["nut"]
    assert nut["count_mae"] == 4.0 and nut["ap50"] == 1.0


def test_overconfident_scores_show_in_calibration():
    data = _dataset()
    predictions = _perfect_predictions(data, score=0.99)
    predictions += [{"image_id": f"img-{i}", "label": "nut", "bbox": [800, 800, 40, 40], "score": 0.99} for i in range(60)]
    nut = de.evaluate(data, predictions, crop_id="almond").labels["nut"]
    assert nut["score_ece"] == pytest.approx(0.99 - 240 / 300, abs=1e-3)


def test_small_test_split_is_insufficient_not_measured_as_success():
    data = _dataset(n_images=10)
    report = de.evaluate(data, _perfect_predictions(data), crop_id="almond")
    assert report.status == de.INSUFFICIENT
    assert report.labels["nut"]["ap50"] == 1.0  # shown, but not accepted as evidence


def test_too_few_growers_is_insufficient():
    data = _dataset()
    for image in data["images"]:
        image["grouping"]["grower"] = "only-one"
    assert de.evaluate(data, _perfect_predictions(data), crop_id="almond").status == de.INSUFFICIENT


def test_leakage_missing_consent_and_bad_labels_refuse_scoring():
    data = _dataset()
    data["images"].append({**_image(999, split="train"), "grouping": dict(data["images"][0]["grouping"])})
    report = de.evaluate(data, _perfect_predictions(data), crop_id="almond")
    assert report.status == de.NOT_MEASURED and report.leakage and report.labels == {}

    data = _dataset()
    data["images"][0]["consent"] = {}
    assert de.evaluate(data, [], crop_id="almond").status == de.NOT_MEASURED

    data = _dataset()
    data["annotations"].append({"image_id": "img-1", "label": "tractor", "bbox": [1, 1, 5, 5]})
    report = de.evaluate(data, [], crop_id="almond")
    assert report.status == de.NOT_MEASURED and any("not in the almond profile" in error for error in report.errors)


def test_only_test_split_is_scored():
    data = _dataset()
    data["images"] += [_image(500 + i, split="train") for i in range(5)]
    data["annotations"] += [{"image_id": f"img-{500 + i}", "label": "nut", "bbox": [1, 1, 5, 5]} for i in range(5)]
    report = de.evaluate(data, _perfect_predictions({"annotations": data["annotations"][:240]}), crop_id="almond")
    assert report.test_images == 60 and report.labels["nut"]["ground_truth_objects"] == 240


def test_unknown_crop_and_cli(tmp_path):
    assert de.evaluate(_dataset(), [], crop_id="dragonfruit").errors == ["unknown crop profile 'dragonfruit'"]
    data = _dataset()
    gt, pred, out = tmp_path / "gt.json", tmp_path / "pred.json", tmp_path / "report.json"
    gt.write_text(json.dumps(data))
    pred.write_text(json.dumps(_perfect_predictions(data)))
    assert de.main([str(gt), str(pred), "--crop", "almond", "--json", str(out)]) == 0
    assert json.loads(out.read_text())["labels"]["nut"]["ap50"] == 1.0

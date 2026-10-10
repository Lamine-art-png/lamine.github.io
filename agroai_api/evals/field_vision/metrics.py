"""Deterministic metric primitives (standard library only).

Proportions carry Wilson score intervals so a reader can see how little a
small reviewed sample proves. Detection metrics follow the usual
definitions: IoU on normalized ``[x, y, w, h]`` boxes and all-point
interpolated average precision at a fixed IoU threshold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    successes: int
    total: int

    @property
    def value(self) -> float | None:
        return self.successes / self.total if self.total else None

    def wilson(self, z: float = Z_95) -> tuple[float, float] | None:
        """Wilson score interval; ``None`` when there is no denominator."""
        if not self.total:
            return None
        n = self.total
        p = self.successes / n
        denominator = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denominator
        margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
        return max(0.0, centre - margin), min(1.0, centre + margin)


def median(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def percentile(values: Iterable[float], q: float) -> float | None:
    """Linear-interpolated percentile, ``q`` in [0, 100]."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * max(0.0, min(q, 100.0)) / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Mean squared error between predicted probability and 0/1 outcome."""
    if not probabilities or len(probabilities) != len(outcomes):
        return None
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities)


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> float | None:
    """Equal-width-bin ECE: sum over bins of |accuracy - confidence| * weight."""
    if not probabilities or len(probabilities) != len(outcomes):
        return None
    totals = [0] * bins
    confidence_sums = [0.0] * bins
    outcome_sums = [0] * bins
    for p, y in zip(probabilities, outcomes):
        index = min(int(p * bins), bins - 1)
        totals[index] += 1
        confidence_sums[index] += p
        outcome_sums[index] += y
    n = len(probabilities)
    return sum(
        abs(outcome_sums[i] / totals[i] - confidence_sums[i] / totals[i]) * totals[i] / n
        for i in range(bins) if totals[i]
    )


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """IoU of two ``[x, y, w, h]`` boxes in the same coordinate space."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = inter_w * inter_h
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def average_precision(
    predictions: Sequence[tuple[str, float, Sequence[float]]],
    ground_truth: dict[str, list[Sequence[float]]],
    iou_threshold: float = 0.5,
) -> float | None:
    """All-point interpolated AP for one class.

    ``predictions``: ``(image_id, score, box)``; ``ground_truth``: image id to
    boxes. Each ground-truth box can be matched once; extra matches are false
    positives. ``None`` when there is no ground truth to recall.
    """
    total_truth = sum(len(boxes) for boxes in ground_truth.values())
    if total_truth == 0:
        return None
    used = {image: [False] * len(boxes) for image, boxes in ground_truth.items()}
    true_positive: list[int] = []
    for image_id, _score, box in sorted(predictions, key=lambda item: -item[1]):
        best, best_index = 0.0, -1
        for index, truth in enumerate(ground_truth.get(image_id, [])):
            overlap = iou(box, truth)
            if overlap > best:
                best, best_index = overlap, index
        if best >= iou_threshold and best_index >= 0 and not used[image_id][best_index]:
            used[image_id][best_index] = True
            true_positive.append(1)
        else:
            true_positive.append(0)
    precisions: list[float] = []
    recalls: list[float] = []
    tp = 0
    for rank, hit in enumerate(true_positive, start=1):
        tp += hit
        precisions.append(tp / rank)
        recalls.append(tp / total_truth)
    # Precision envelope, then area under the step curve.
    for index in range(len(precisions) - 2, -1, -1):
        precisions[index] = max(precisions[index], precisions[index + 1])
    area, previous_recall = 0.0, 0.0
    for precision, recall in zip(precisions, recalls):
        area += (recall - previous_recall) * precision
        previous_recall = recall
    return area


def count_errors(predicted: Sequence[float], actual: Sequence[float]) -> dict[str, float | None]:
    """MAE always; MAPE only over items whose true count is non-zero."""
    if not predicted or len(predicted) != len(actual):
        return {"mae": None, "mape": None, "n": 0}
    mae = sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)
    nonzero = [(p, a) for p, a in zip(predicted, actual) if a]
    mape = sum(abs(p - a) / abs(a) for p, a in nonzero) / len(nonzero) if nonzero else None
    return {"mae": mae, "mape": mape, "n": len(predicted)}


def interval_coverage(intervals: Sequence[tuple[float, float]], actual: Sequence[float]) -> float | None:
    """Share of true values inside their predicted interval (inclusive)."""
    if not intervals or len(intervals) != len(actual):
        return None
    return sum(1 for (low, high), value in zip(intervals, actual) if low <= value <= high) / len(actual)

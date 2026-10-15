"""Cross-frame de-duplication and honest counts for detected objects.

A walk-and-talk video shows the same fruit, clusters, or plants in many
frames. Summing per-frame detections would count each object repeatedly.

Two regimes:

- **Dense frames** (median spacing within ``max_tracking_interval_s``):
  detections of the same label are associated across consecutive frames by
  box overlap (greedy IoU matching with a short gap allowance). A track
  seen in at least ``min_hits`` frames is a confirmed unique object;
  single-frame tracks are reported separately as unconfirmed.
- **Sparse frames** (the durable pipeline samples a few frames seconds
  apart, and photos are independent shots): the camera has moved too far
  for overlap to identify the same object, so no unique count is claimed.
  The report gives the largest single-frame count as a lower bound and the
  sum of frame counts as an upper bound, never as a count.

Counts describe only what the camera observed. Converting them into density
or field production needs a documented sampling design and calibration (see
``crop_estimation``).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.field_detection import Detection, DetectionResult

TRACKING_METHOD = "greedy_iou_tracking_v1"
LOWER_BOUND_METHOD = "max_single_frame_lower_bound"


def _iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = inter_w * inter_h
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: int
    label: str
    box: list[float]
    last_frame: int
    hits: int = 1
    best_score: float = 0.0
    frames: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CountSummary:
    label: str
    count_method: str
    frames_considered: int
    per_frame_counts: list[int]
    max_single_frame_count: int
    sum_of_frame_counts: int
    confirmed_unique_count: int | None = None
    unconfirmed_single_frame_tracks: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count_method": self.count_method,
            "frames_considered": self.frames_considered,
            "per_frame_counts": self.per_frame_counts,
            "observed_lower_bound": self.max_single_frame_count,
            "sum_of_frame_counts_upper_bound": self.sum_of_frame_counts,
            "confirmed_unique_count": self.confirmed_unique_count,
            "unconfirmed_single_frame_tracks": self.unconfirmed_single_frame_tracks,
            "coverage": "observed_frames_only",
        }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def track_label(
    frames: list[list[Detection]],
    label: str,
    *,
    frame_refs: list[dict[str, Any]] | None = None,
    iou_threshold: float = 0.3,
    max_gap: int = 1,
) -> list[Track]:
    """Associate ``label`` detections across ordered frames."""
    tracks: list[Track] = []
    active: list[Track] = []
    next_id = 1
    for index, detections in enumerate(frames):
        candidates = [item for item in detections if item.label == label]
        active = [track for track in active if index - track.last_frame <= max_gap + 1]
        pairs = sorted(
            ((_iou(track.box, item.box), t, d) for t, track in enumerate(active) for d, item in enumerate(candidates)),
            key=lambda pair: -pair[0],
        )
        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        for overlap, t, d in pairs:
            if overlap < iou_threshold:
                break
            if t in matched_tracks or d in matched_detections:
                continue
            matched_tracks.add(t)
            matched_detections.add(d)
            track, item = active[t], candidates[d]
            track.box, track.last_frame = item.box, index
            track.hits += 1
            track.best_score = max(track.best_score, item.score)
            if frame_refs:
                track.frames.append(frame_refs[index])
        for d, item in enumerate(candidates):
            if d in matched_detections:
                continue
            track = Track(track_id=next_id, label=label, box=item.box, last_frame=index, best_score=item.score,
                          frames=[frame_refs[index]] if frame_refs else [])
            next_id += 1
            tracks.append(track)
            active.append(track)
    return tracks


def summarize_counts(
    results: Iterable[DetectionResult],
    *,
    excluded_frames: set[tuple[str | None, float | None]] | None = None,
    max_tracking_interval_s: float = 0.5,
    min_hits: int = 2,
    iou_threshold: float = 0.3,
) -> dict[str, Any]:
    """Count detections per label without double counting across frames.

    ``excluded_frames`` holds ``(asset_id, frame_timestamp_seconds)`` pairs
    to leave out (for example frames the general vision layer judged poor).
    """
    excluded = excluded_frames or set()
    by_asset: dict[str | None, list[DetectionResult]] = defaultdict(list)
    skipped = 0
    for result in results:
        if result.status != "ok":
            continue
        key = (result.frame.asset_id, result.frame.frame_timestamp_seconds)
        if key in excluded:
            skipped += 1
            continue
        by_asset[result.frame.asset_id or f"image:{id(result)}"].append(result)

    labels = sorted({item.label for rows in by_asset.values() for row in rows for item in row.detections})
    per_asset: list[dict[str, Any]] = []
    totals: dict[str, dict[str, Any]] = {}
    for asset_id, rows in by_asset.items():
        rows.sort(key=lambda row: (row.frame.frame_timestamp_seconds is None, row.frame.frame_timestamp_seconds or 0.0))
        times = [row.frame.frame_timestamp_seconds for row in rows if row.frame.frame_timestamp_seconds is not None]
        spacing = _median([later - earlier for earlier, later in zip(times, times[1:])])
        dense = len(rows) >= 2 and len(times) == len(rows) and spacing is not None and spacing <= max_tracking_interval_s
        frames = [row.detections for row in rows]
        refs = [row.frame.to_dict() for row in rows]
        asset_counts: dict[str, Any] = {}
        for label in labels:
            per_frame = [sum(1 for item in detections if item.label == label) for detections in frames]
            summary = CountSummary(
                label=label,
                count_method=TRACKING_METHOD if dense else LOWER_BOUND_METHOD,
                frames_considered=len(rows),
                per_frame_counts=per_frame,
                max_single_frame_count=max(per_frame, default=0),
                sum_of_frame_counts=sum(per_frame),
            )
            if dense:
                tracks = track_label(frames, label, frame_refs=refs, iou_threshold=iou_threshold)
                summary.confirmed_unique_count = sum(1 for track in tracks if track.hits >= min_hits)
                summary.unconfirmed_single_frame_tracks = sum(1 for track in tracks if track.hits < min_hits)
            asset_counts[label] = summary.to_dict()
            total = totals.setdefault(label, {"label": label, "observed_lower_bound": 0, "sum_upper_bound": 0})
            lower = summary.confirmed_unique_count if summary.confirmed_unique_count is not None else summary.max_single_frame_count
            # Different assets may show the same plants, so the lower bound
            # across assets is the largest single-asset lower bound.
            total["observed_lower_bound"] = max(total["observed_lower_bound"], lower)
            total["sum_upper_bound"] += summary.sum_of_frame_counts
        per_asset.append({
            "asset_id": None if str(asset_id).startswith("image:") else asset_id,
            "frames": len(rows),
            "median_frame_spacing_s": spacing,
            "tracking_supported": dense,
            "counts": asset_counts,
        })
    return {
        "labels": labels,
        "per_asset": per_asset,
        "totals": list(totals.values()),
        "frames_excluded": skipped,
        "coverage": "observed_frames_only",
        "extrapolation": "none",
    }

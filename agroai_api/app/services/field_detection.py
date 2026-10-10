"""Provider-neutral crop object detection for Field Intelligence.

This is the specialized detection lane that sits beside the general
vision-language analysis in ``field_vision`` (which stays the contextual
reasoning and fallback layer). A detector returns boxes, optional masks,
labels from the crop profile vocabulary, and scores; this module validates
every value, maps geometry into the displayed image frame, and records model
provenance.

There are no approved detector weights or labelled crop datasets yet, so the
default provider is ``DisabledDetectionProvider`` and nothing is detected.
``HttpDetectionProvider`` connects a self-hosted inference service (for
example an Apache-2.0 RT-DETR or YOLOX export served with ONNX Runtime) only
when ``FIELD_DETECTION_ENABLED`` is true and an https endpoint is configured.

HTTP inference contract (JSON)::

    POST <FIELD_DETECTION_ENDPOINT>
    {"image": <base64>, "content_type": "image/jpeg", "crop_profile": "wine_grape",
     "labels": ["cluster", ...], "max_detections": 300}

    200 {"model": {"id": "...", "version": "...", "license": "..."},
         "image": {"width": 1280, "height": 960, "orientation_applied": false},
         "detections": [{"label": "cluster", "score": 0.83,
                         "box": [x, y, w, h], "box_format": "normalized_xywh" | "pixel_xywh",
                         "mask": [[u, v], ...]}]}

Detector scores are uncalibrated until a calibration has been fitted on
reviewed held-out data; they are labelled ``detector_score_uncalibrated``.
"""
from __future__ import annotations

import base64
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.services.crop_profiles import CropProfile
from app.services.image_geometry import box_to_display, jpeg_exif_orientation, normalize_box, polygon_to_display

DETECTION_CONTRACT_VERSION = "field-detection/1"
SCORE_KIND = "detector_score_uncalibrated"
MAX_DETECTIONS = 300
MAX_MASK_POINTS = 256
MAX_IMAGE_BYTES = 8 * 1024 * 1024
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class FrameRef:
    asset_id: str | None = None
    media_kind: str | None = None
    frame_timestamp_seconds: float | None = None
    frame_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class Detection:
    label: str
    score: float
    box: list[float]  # normalized [x, y, w, h] in the displayed image frame
    mask: list[list[float]] | None = None  # normalized polygon, displayed frame
    score_kind: str = SCORE_KIND

    def to_dict(self) -> dict[str, Any]:
        row = {"label": self.label, "score": self.score, "score_kind": self.score_kind, "box": self.box}
        if self.mask:
            row["mask"] = self.mask
        return row


@dataclass
class DetectionResult:
    status: str  # ok | disabled | unavailable | failed
    frame: FrameRef
    detections: list[Detection] = field(default_factory=list)
    model_id: str | None = None
    model_version: str | None = None
    model_license: str | None = None
    provider: str = "none"
    latency_ms: int | None = None
    error: str | None = None
    retryable: bool = False
    dropped: dict[str, int] = field(default_factory=dict)
    image_size: tuple[int, int] | None = None
    orientation_corrected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "frame": self.frame.to_dict(),
            "detections": [item.to_dict() for item in self.detections],
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_license": self.model_license,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "dropped": self.dropped,
            "image_size": list(self.image_size) if self.image_size else None,
            "orientation_corrected": self.orientation_corrected,
        }


class DetectionProvider(Protocol):
    name: str

    def detect(self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef) -> DetectionResult: ...


class DisabledDetectionProvider:
    """Default: no validated detector exists, so nothing is detected."""

    name = "disabled"

    def __init__(self, reason: str = "no_validated_detector_weights") -> None:
        self.reason = reason

    def detect(self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef) -> DetectionResult:
        return DetectionResult(status="disabled", frame=frame, provider=self.name, error=self.reason)


def _bounded_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def parse_detector_response(
    payload: Any, *, profile: CropProfile, frame: FrameRef, image: bytes, content_type: str | None,
) -> DetectionResult:
    """Strictly validate a detector response against the contract."""
    if not isinstance(payload, dict):
        return DetectionResult(status="failed", frame=frame, error="detector_response_not_object")
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_id = str(model.get("id") or "").strip()[:200]
    if not model_id:
        return DetectionResult(status="failed", frame=frame, error="detector_model_id_missing")
    image_info = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    width = image_info.get("width") if isinstance(image_info.get("width"), int) else None
    height = image_info.get("height") if isinstance(image_info.get("height"), int) else None
    orientation = 1
    if not image_info.get("orientation_applied") and (content_type or "").lower() == "image/jpeg":
        orientation = jpeg_exif_orientation(image)

    allowed = set(profile.detection_labels)
    dropped: dict[str, int] = {}
    detections: list[Detection] = []
    raw = payload.get("detections") if isinstance(payload.get("detections"), list) else []
    if len(raw) > MAX_DETECTIONS:
        dropped["over_limit"] = len(raw) - MAX_DETECTIONS
    for item in raw[:MAX_DETECTIONS]:
        if not isinstance(item, dict):
            dropped["malformed"] = dropped.get("malformed", 0) + 1
            continue
        label = str(item.get("label") or "").strip()
        if label not in allowed:
            dropped["label_not_in_profile"] = dropped.get("label_not_in_profile", 0) + 1
            continue
        score = _bounded_score(item.get("score"))
        if score is None:
            dropped["invalid_score"] = dropped.get("invalid_score", 0) + 1
            continue
        box = item.get("box")
        normalized = normalize_box(box, box_format=str(item.get("box_format") or "normalized_xywh"), width=width, height=height) \
            if isinstance(box, (list, tuple)) else None
        if normalized is None:
            dropped["invalid_box"] = dropped.get("invalid_box", 0) + 1
            continue
        mask = None
        raw_mask = item.get("mask")
        if isinstance(raw_mask, list) and 3 <= len(raw_mask) <= MAX_MASK_POINTS:
            points = []
            for point in raw_mask:
                if (isinstance(point, (list, tuple)) and len(point) == 2
                        and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                and math.isfinite(value) and -0.02 <= value <= 1.02 for value in point)):
                    points.append([min(1.0, max(0.0, float(point[0]))), min(1.0, max(0.0, float(point[1])))])
            mask = points if len(points) == len(raw_mask) else None
            if mask is None:
                dropped["invalid_mask"] = dropped.get("invalid_mask", 0) + 1
        if orientation != 1:
            normalized = [round(value, 6) for value in box_to_display(normalized, orientation)]
            mask = polygon_to_display(mask, orientation) if mask else None
        detections.append(Detection(label=label, score=round(score, 4), box=normalized, mask=mask))

    size = (width, height) if width and height else None
    return DetectionResult(
        status="ok", frame=frame, detections=detections, model_id=model_id,
        model_version=str(model.get("version") or "").strip()[:100] or None,
        model_license=str(model.get("license") or "").strip()[:100] or None,
        dropped=dropped, image_size=size, orientation_corrected=orientation != 1,
    )


class HttpDetectionProvider:
    name = "http_detector"

    def __init__(self, endpoint: str, api_key: str, *, timeout_seconds: float = 30.0, client: httpx.Client | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = max(2.0, float(timeout_seconds))
        self._client = client

    def detect(self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef) -> DetectionResult:
        if not image or len(image) > MAX_IMAGE_BYTES:
            return DetectionResult(status="failed", frame=frame, provider=self.name, error="image_outside_detector_bound")
        started = time.monotonic()
        body = {
            "image": base64.b64encode(image).decode("ascii"),
            "content_type": content_type or "application/octet-stream",
            "crop_profile": profile.crop_id,
            "labels": list(profile.detection_labels),
            "max_detections": MAX_DETECTIONS,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            if self._client is not None:
                response = self._client.post(self.endpoint, json=body, headers=headers, timeout=self.timeout)
            else:
                response = httpx.post(self.endpoint, json=body, headers=headers, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed failure
            return DetectionResult(
                status="failed", frame=frame, provider=self.name, error=exc.__class__.__name__, retryable=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return DetectionResult(
                status="failed", frame=frame, provider=self.name, latency_ms=latency,
                error=f"detector_http_{response.status_code}", retryable=response.status_code in RETRYABLE_HTTP,
            )
        try:
            payload = response.json()
        except ValueError:
            return DetectionResult(status="failed", frame=frame, provider=self.name, latency_ms=latency, error="detector_response_not_json")
        result = parse_detector_response(payload, profile=profile, frame=frame, image=image, content_type=content_type)
        result.provider = self.name
        result.latency_ms = latency
        return result


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def detection_enabled() -> bool:
    return _env("FIELD_DETECTION_ENABLED").lower() in {"1", "true", "yes", "on"}


def _endpoint_allowed(endpoint: str) -> bool:
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment


def get_detection_provider() -> DetectionProvider:
    """Disabled unless explicitly enabled with a valid https endpoint and key."""
    if not detection_enabled():
        return DisabledDetectionProvider()
    endpoint = _env("FIELD_DETECTION_ENDPOINT")
    key = _env("FIELD_DETECTION_API_KEY")
    if not endpoint or not key:
        return DisabledDetectionProvider("detector_not_configured")
    if not _endpoint_allowed(endpoint):
        return DisabledDetectionProvider("detector_endpoint_rejected")
    try:
        timeout = float(_env("FIELD_DETECTION_TIMEOUT_SECONDS") or 30.0)
    except ValueError:
        timeout = 30.0
    return HttpDetectionProvider(endpoint, key, timeout_seconds=timeout)

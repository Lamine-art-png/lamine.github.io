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
import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.services import crop_model_registry
from app.services.crop_profiles import CropProfile
from app.services.image_geometry import box_to_display, jpeg_exif_orientation, normalize_box, polygon_to_display

DETECTION_CONTRACT_VERSION = "field-detection/1"
SCORE_KIND = "detector_score_uncalibrated"
MAX_DETECTIONS = 300
MAX_MASK_POINTS = 256
MAX_IMAGE_BYTES = 8 * 1024 * 1024
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
# 300 detections with 256-point masks fit well inside this; anything larger is refused.
MAX_DETECTOR_RESPONSE_BYTES = 4 * 1024 * 1024
_STREAM_CHUNK_BYTES = 64 * 1024


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
    reported_model_license: str | None = None   # as stated by the detector; not verified
    model_verification: str = "unregistered_unverified"  # or "registry_verified"
    registered_model_license: str | None = None
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
            "reported_model_license": self.reported_model_license,
            "model_verification": self.model_verification,
            "registered_model_license": self.registered_model_license,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "dropped": self.dropped,
            "image_size": list(self.image_size) if self.image_size else None,
            "orientation_corrected": self.orientation_corrected,
        }


class DetectionProvider(Protocol):
    name: str

    def detect(
        self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef, *, timeout_seconds: float | None = None,
    ) -> DetectionResult: ...


MIN_FRAME_SECONDS = 2.0
_SETUP_PHASE_CAP_SECONDS = 5.0


def bounded_timeout(configured_seconds: float, remaining_seconds: float | None = None) -> httpx.Timeout:
    """Per-operation httpx timeouts sized from the frame's budget.

    httpx applies these to each socket operation, not to the whole request,
    so they only stop a stalled connection; ``HttpDetectionProvider`` also
    enforces the frame's wall-clock deadline between chunks. The budget is
    min(configured, remaining); pool, connect and write get at most a
    quarter of it (capped at 5 s) and read gets the rest.
    """
    total = float(configured_seconds)
    if remaining_seconds is not None:
        total = min(total, float(remaining_seconds))
    total = max(total, 0.1)
    setup = min(_SETUP_PHASE_CAP_SECONDS, total / 4)
    return httpx.Timeout(connect=setup, write=setup, pool=setup, read=total - 3 * setup)


class DisabledDetectionProvider:
    """Default: no validated detector exists, so nothing is detected."""

    name = "disabled"

    def __init__(self, reason: str = "no_validated_detector_weights") -> None:
        self.reason = reason

    def detect(
        self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef, *, timeout_seconds: float | None = None,
    ) -> DetectionResult:
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
    version = str(model.get("version") or "").strip()[:100] or None
    # Upstream identity strings are self-attested; only the server registry verifies.
    registered = crop_model_registry.verified_detector(model_id, version)
    if registered is not None and profile.crop_id not in registered.crop_ids:
        registered = None
    return DetectionResult(
        status="ok", frame=frame, detections=detections, model_id=model_id, model_version=version,
        reported_model_license=str(model.get("license") or "").strip()[:100] or None,
        model_verification="registry_verified" if registered is not None else "unregistered_unverified",
        registered_model_license=registered.license if registered is not None else None,
        dropped=dropped, image_size=size, orientation_corrected=orientation != 1,
    )


class _FrameDeadlineExceeded(Exception):
    pass


class _ResponseTooLarge(Exception):
    pass


_now = time.monotonic  # test seam


def _deadline_chunks(payload: bytes, deadline: float):
    """Request body in chunks, stopping once the frame's deadline passes."""
    for offset in range(0, len(payload), _STREAM_CHUNK_BYTES):
        if _now() > deadline:
            raise _FrameDeadlineExceeded
        yield payload[offset:offset + _STREAM_CHUNK_BYTES]


class HttpDetectionProvider:
    """Calls a self-hosted detector over HTTPS.

    The frame's budget is a wall-clock deadline. The HTTP exchange (DNS,
    connect, upload, headers, body) runs on a helper thread and the caller
    waits only until the deadline, then records the frame as
    ``detector_frame_time_budget_exceeded``. httpx timeouts apply to each
    socket operation, so on their own a slow uplink, trickled headers or
    body, or a stream of informational (1xx) responses could hold a frame
    indefinitely. The abandoned exchange stops at its next chunk (upload
    and body are checked against the deadline) or socket timeout; its
    socket is never closed from another thread, where a reused descriptor
    could belong to an unrelated connection.
    """

    name = "http_detector"

    def __init__(self, endpoint: str, api_key: str, *, timeout_seconds: float = 30.0, client: httpx.Client | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = max(2.0, float(timeout_seconds))
        self._client = client

    def detect(
        self, image: bytes, content_type: str | None, profile: CropProfile, frame: FrameRef, *, timeout_seconds: float | None = None,
    ) -> DetectionResult:
        if not image or len(image) > MAX_IMAGE_BYTES:
            return DetectionResult(status="failed", frame=frame, provider=self.name, error="image_outside_detector_bound")
        started = _now()
        body = {
            "image": base64.b64encode(image).decode("ascii"),
            "content_type": content_type or "application/octet-stream",
            "crop_profile": profile.crop_id,
            "labels": list(profile.detection_labels),
            "max_detections": MAX_DETECTIONS,
        }
        payload_bytes = json.dumps(body).encode("utf-8")
        # An explicit length keeps the streamed upload a plain (not chunked) request body.
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                   "Content-Length": str(len(payload_bytes))}
        timeout = bounded_timeout(self.timeout, timeout_seconds)
        budget = self.timeout if timeout_seconds is None else min(self.timeout, float(timeout_seconds))
        deadline = started + max(budget, 0.1)
        outcome: dict[str, Any] = {}

        def exchange() -> None:
            raw = bytearray()
            try:
                # Built inside the guard: a bad proxy environment is a typed failure, not a crashed job.
                client = self._client or httpx.Client()
                try:
                    with client.stream("POST", self.endpoint, content=_deadline_chunks(payload_bytes, deadline),
                                       headers=headers, timeout=timeout) as response:
                        if response.status_code < 400:
                            for chunk in response.iter_bytes():
                                if _now() > deadline:
                                    raise _FrameDeadlineExceeded
                                raw.extend(chunk)
                                if len(raw) > MAX_DETECTOR_RESPONSE_BYTES:
                                    raise _ResponseTooLarge
                        if _now() > deadline:  # e.g. trailers trickled in after the body
                            raise _FrameDeadlineExceeded
                        outcome["status_code"] = response.status_code
                finally:
                    if self._client is None:
                        client.close()
                outcome["raw"] = bytes(raw)
            except Exception as exc:  # noqa: BLE001 - surfaced as a typed failure below
                outcome["error"] = exc

        worker = threading.Thread(target=exchange, name="field-detection-frame", daemon=True)
        worker.start()
        worker.join(max(0.0, deadline - _now()))
        # An abandoned helper keeps writing to ``outcome``; the caller reads a separate result.
        settled = {"error": _FrameDeadlineExceeded()} if worker.is_alive() else dict(outcome)
        exc = settled.get("error")
        if exc is not None:
            if isinstance(exc, _ResponseTooLarge):
                error, retryable = "detector_response_too_large", False
            elif isinstance(exc, _FrameDeadlineExceeded) or _now() > deadline:
                error, retryable = "detector_frame_time_budget_exceeded", True
            else:
                error, retryable = exc.__class__.__name__, True
            return DetectionResult(status="failed", frame=frame, provider=self.name, error=error, retryable=retryable,
                                   latency_ms=int((_now() - started) * 1000))
        status_code, raw = int(settled["status_code"]), settled["raw"]
        latency = int((_now() - started) * 1000)
        if status_code >= 400:
            return DetectionResult(
                status="failed", frame=frame, provider=self.name, latency_ms=latency,
                error=f"detector_http_{status_code}", retryable=status_code in RETRYABLE_HTTP,
            )
        try:
            payload = json.loads(raw)
        except ValueError:
            return DetectionResult(status="failed", frame=frame, provider=self.name, latency_ms=latency, error="detector_response_not_json")
        result = parse_detector_response(payload, profile=profile, frame=frame, image=image, content_type=content_type)
        result.provider = self.name
        result.latency_ms = latency
        return result


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def detection_enabled() -> bool:
    """Global kill switch: false (the default) stops all specialized detection."""
    return _env("FIELD_DETECTION_ENABLED").lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(_env(name) or default)
    except ValueError:
        value = default
    return max(low, min(value, high))


def _bounded_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(_env(name) or default)
    except ValueError:
        value = default
    return max(low, min(value, high)) if value == value else default  # NaN falls back to the default


@dataclass(frozen=True)
class DetectionLimits:
    max_frames_per_observation: int
    observation_budget_seconds: float
    daily_frame_budget_per_organization: int


def detection_limits() -> DetectionLimits:
    return DetectionLimits(
        max_frames_per_observation=_bounded_int("FIELD_DETECTION_MAX_FRAMES_PER_OBSERVATION", 8, 1, 8),
        observation_budget_seconds=_bounded_float("FIELD_DETECTION_OBSERVATION_BUDGET_SECONDS", 60.0, 5.0, 300.0),
        daily_frame_budget_per_organization=_bounded_int("FIELD_DETECTION_DAILY_FRAME_BUDGET", 200, 0, 100_000),
    )


def detection_allowed_for(organization_id: str | None) -> tuple[bool, str]:
    """Kill switch plus a fail-closed canary allowlist of organization ids."""
    if not detection_enabled():
        return False, "detection_disabled"
    allowlist = {item.strip() for item in _env("FIELD_DETECTION_ORG_ALLOWLIST").split(",") if item.strip()}
    if not organization_id or organization_id not in allowlist:
        return False, "organization_not_in_detection_canary"
    return True, "allowed"


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

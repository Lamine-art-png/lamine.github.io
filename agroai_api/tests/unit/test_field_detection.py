"""Detection lane: profiles, geometry, strict provider validation, counting."""
from __future__ import annotations

import json
import struct

import httpx
import pytest

from app.services import crop_profiles
from app.services import field_detection as detection
from app.services import image_geometry as geometry
from app.services.detection_tracking import LOWER_BOUND_METHOD, TRACKING_METHOD, summarize_counts, track_label

GRAPE = crop_profiles.get_profile("wine_grape")


def _jpeg_with_orientation(orientation: int, byte_order: str = "MM") -> bytes:
    endian = ">" if byte_order == "MM" else "<"
    ifd = struct.pack(f"{endian}H", 1) + struct.pack(f"{endian}HHIH", 0x0112, 3, 1, orientation) + b"\x00\x00" + struct.pack(f"{endian}I", 0)
    tiff = byte_order.encode() + struct.pack(f"{endian}HI", 42, 8) + ifd
    segment = b"Exif\x00\x00" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(segment) + 2) + segment + b"\xff\xd9"


# ---------------------------------------------------------------------------
# Crop profiles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "crop_id"),
    [("Almonds", "almond"), ("milho", "corn"), ("Maíz", "corn"), ("wine grapes", "wine_grape"), ("Café", "coffee"),
     ("tomatoes", "tomato"), ("dragonfruit", None), ("", None), (None, None)],
)
def test_resolve_profile(text, crop_id):
    profile = crop_profiles.resolve_profile(text)
    assert (profile.crop_id if profile else None) == crop_id


def test_no_profile_claims_validation_and_tomato_is_benchmark_only():
    profiles = crop_profiles.all_profiles()
    assert profiles and all(profile.validation_status == "unvalidated" for profile in profiles)
    assert crop_profiles.get_profile("tomato").benchmark_only is True
    assert [profile.crop_id for profile in profiles if profile.benchmark_only] == ["tomato"]


def test_only_conventional_degree_day_method_is_supplied():
    corn = crop_profiles.get_profile("corn").degree_day_method
    assert (corn.base_c, corn.upper_cutoff_c) == (10.0, 30.0)
    # No profile ships a maturity target: those are variety-specific inputs.
    for profile in crop_profiles.all_profiles():
        assert "target" not in str(profile.to_dict()["degree_day_method"]).lower()


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("orientation", range(1, 9))
@pytest.mark.parametrize("byte_order", ["MM", "II"])
def test_exif_orientation_is_read(orientation, byte_order):
    assert geometry.jpeg_exif_orientation(_jpeg_with_orientation(orientation, byte_order)) == orientation


@pytest.mark.parametrize("data", [b"", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xd9", b"\xff\xd8\xff\xe1\x00\x08Exif\x00\x00"])
def test_missing_or_broken_exif_defaults_to_upright(data):
    assert geometry.jpeg_exif_orientation(data) == 1


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (1, [0.1, 0.2, 0.3, 0.4]),
        (2, [0.6, 0.2, 0.3, 0.4]),
        (3, [0.6, 0.4, 0.3, 0.4]),
        (4, [0.1, 0.4, 0.3, 0.4]),
        (5, [0.2, 0.1, 0.4, 0.3]),
        (6, [0.4, 0.1, 0.4, 0.3]),
        (7, [0.4, 0.6, 0.4, 0.3]),
        (8, [0.2, 0.6, 0.4, 0.3]),
    ],
)
def test_box_to_display(orientation, expected):
    assert geometry.box_to_display([0.1, 0.2, 0.3, 0.4], orientation) == pytest.approx(expected)


def test_normalize_box_rules():
    assert geometry.normalize_box([10, 20, 30, 40], box_format="pixel_xywh", width=100, height=200) == [0.1, 0.1, 0.3, 0.2]
    assert geometry.normalize_box([10, 20, 30, 40], box_format="pixel_xywh", width=None, height=200) is None
    assert geometry.normalize_box([-0.01, 0, 0.5, 0.5], box_format="normalized_xywh", width=None, height=None) == [0.0, 0.0, 0.49, 0.5]
    assert geometry.normalize_box([0.5, 0.5, 0.8, 0.2], box_format="normalized_xywh", width=None, height=None) is None
    assert geometry.normalize_box([0.1, 0.1, 0, 0.2], box_format="normalized_xywh", width=None, height=None) is None
    assert geometry.normalize_box([0.1, float("nan"), 0.1, 0.1], box_format="normalized_xywh", width=None, height=None) is None
    assert geometry.normalize_box([0.1, 0.1, 0.1, 0.1], box_format="xyxy", width=None, height=None) is None


# ---------------------------------------------------------------------------
# Provider selection and response validation
# ---------------------------------------------------------------------------

def test_detection_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FIELD_DETECTION_ENABLED", raising=False)
    provider = detection.get_detection_provider()
    assert isinstance(provider, detection.DisabledDetectionProvider)
    result = provider.detect(b"img", "image/jpeg", GRAPE, detection.FrameRef(asset_id="a"))
    assert result.status == "disabled" and result.detections == []
    assert result.error == "no_validated_detector_weights"


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({"FIELD_DETECTION_ENABLED": "true"}, "detector_not_configured"),
        ({"FIELD_DETECTION_ENABLED": "true", "FIELD_DETECTION_ENDPOINT": "http://detector.internal/infer", "FIELD_DETECTION_API_KEY": "k"}, "detector_endpoint_rejected"),
        ({"FIELD_DETECTION_ENABLED": "true", "FIELD_DETECTION_ENDPOINT": "https://user:pw@detector.internal/infer", "FIELD_DETECTION_API_KEY": "k"}, "detector_endpoint_rejected"),
    ],
)
def test_enabled_but_unsafe_configuration_stays_disabled(monkeypatch, env, reason):
    for key in ("FIELD_DETECTION_ENABLED", "FIELD_DETECTION_ENDPOINT", "FIELD_DETECTION_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    provider = detection.get_detection_provider()
    assert isinstance(provider, detection.DisabledDetectionProvider)
    assert provider.reason == reason


def test_enabled_https_configuration_uses_http_provider(monkeypatch):
    monkeypatch.setenv("FIELD_DETECTION_ENABLED", "true")
    monkeypatch.setenv("FIELD_DETECTION_ENDPOINT", "https://detector.internal/infer")
    monkeypatch.setenv("FIELD_DETECTION_API_KEY", "test-key")
    monkeypatch.setenv("FIELD_DETECTION_TIMEOUT_SECONDS", "not-a-number")
    provider = detection.get_detection_provider()
    assert isinstance(provider, detection.HttpDetectionProvider)
    assert provider.timeout == 30.0


def _payload(**overrides):
    payload = {
        "model": {"id": "rtdetr-grape-test", "version": "0.0-test", "license": "Apache-2.0"},
        "image": {"width": 1000, "height": 500, "orientation_applied": True},
        "detections": [
            {"label": "cluster", "score": 0.9, "box": [0.1, 0.2, 0.2, 0.2]},
            {"label": "cluster", "score": 0.7, "box": [100, 100, 200, 100], "box_format": "pixel_xywh"},
            {"label": "tractor", "score": 0.99, "box": [0.1, 0.1, 0.1, 0.1]},
            {"label": "cluster", "score": 9, "box": [0.1, 0.1, 0.1, 0.1]},
            {"label": "cluster", "score": 0.8, "box": [0.9, 0.9, 0.5, 0.5]},
            {"label": "berry", "score": 0.6, "box": [0.4, 0.4, 0.1, 0.1], "mask": [[0.4, 0.4], [0.5, 0.4], [0.45, 0.5]]},
            {"label": "berry", "score": 0.6, "box": [0.4, 0.4, 0.1, 0.1], "mask": [[0.4, 0.4], [5, 0.4], [0.45, 0.5]]},
            "garbage",
        ],
    }
    payload.update(overrides)
    return payload


def test_parse_detector_response_is_strict():
    result = detection.parse_detector_response(_payload(), profile=GRAPE, frame=detection.FrameRef(asset_id="a"), image=b"x", content_type="image/png")
    assert result.status == "ok"
    assert result.model_id == "rtdetr-grape-test" and result.reported_model_license == "Apache-2.0"
    # Upstream identity is self-attested: unregistered models are never "verified".
    assert result.model_verification == "unregistered_unverified"
    assert result.registered_model_license is None
    assert [item.label for item in result.detections] == ["cluster", "cluster", "berry", "berry"]
    assert result.detections[1].box == [0.1, 0.2, 0.2, 0.2]  # pixel box normalized
    assert result.detections[2].mask is not None
    assert result.detections[3].mask is None
    assert all(item.score_kind == "detector_score_uncalibrated" for item in result.detections)
    assert result.dropped == {"label_not_in_profile": 1, "invalid_score": 1, "invalid_box": 1, "invalid_mask": 1, "malformed": 1}


def test_response_without_model_identity_is_rejected():
    result = detection.parse_detector_response(_payload(model={}), profile=GRAPE, frame=detection.FrameRef(), image=b"x", content_type="image/png")
    assert result.status == "failed" and result.error == "detector_model_id_missing"


def test_exif_rotation_is_corrected_when_detector_did_not_apply_it():
    image = _jpeg_with_orientation(6)
    payload = _payload(image={"width": 1000, "height": 500, "orientation_applied": False},
                       detections=[{"label": "cluster", "score": 0.9, "box": [0.1, 0.2, 0.3, 0.4]}])
    result = detection.parse_detector_response(payload, profile=GRAPE, frame=detection.FrameRef(), image=image, content_type="image/jpeg")
    assert result.orientation_corrected is True
    assert result.detections[0].box == pytest.approx([0.4, 0.1, 0.4, 0.3])


def test_http_provider_round_trip_and_failures():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_payload(detections=[{"label": "cluster", "score": 0.5, "box": [0.1, 0.1, 0.2, 0.2]}]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = detection.HttpDetectionProvider("https://detector.internal/infer", "test-key", client=client)
        result = provider.detect(b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef(asset_id="a", frame_timestamp_seconds=1.0))
    assert result.status == "ok" and result.provider == "http_detector" and len(result.detections) == 1
    assert calls[0].headers["authorization"] == "Bearer test-key"

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        failed = detection.HttpDetectionProvider("https://detector.internal/infer", "k", client=client).detect(b"x", "image/png", GRAPE, detection.FrameRef())
    assert failed.status == "failed" and failed.error == "detector_http_503" and failed.retryable

    too_big = detection.HttpDetectionProvider("https://d.internal", "k").detect(b"", "image/png", GRAPE, detection.FrameRef())
    assert too_big.error == "image_outside_detector_bound"


# ---------------------------------------------------------------------------
# Tracking and counts
# ---------------------------------------------------------------------------

def _det(box, label="cluster", score=0.8):
    return detection.Detection(label=label, score=score, box=box)


def _result(asset, t, boxes, label="cluster"):
    return detection.DetectionResult(
        status="ok", frame=detection.FrameRef(asset_id=asset, frame_timestamp_seconds=t),
        detections=[_det(box, label) for box in boxes],
    )


def test_tracker_does_not_double_count_the_same_object_in_dense_frames():
    # Two clusters drifting slowly across 5 frames 0.2 s apart, plus one spurious single-frame box.
    frames = []
    for i in range(5):
        boxes = [[0.10 + 0.01 * i, 0.2, 0.1, 0.1], [0.60 + 0.01 * i, 0.5, 0.1, 0.1]]
        if i == 2:
            boxes.append([0.85, 0.85, 0.05, 0.05])
        frames.append(_result("video-1", i * 0.2, boxes))
    summary = summarize_counts(frames)
    counts = summary["per_asset"][0]["counts"]["cluster"]
    assert summary["per_asset"][0]["tracking_supported"] is True
    assert counts["count_method"] == TRACKING_METHOD
    assert counts["confirmed_unique_count"] == 2
    assert counts["unconfirmed_single_frame_tracks"] == 1
    assert counts["sum_of_frame_counts_upper_bound"] == 11
    assert summary["totals"] == [{"label": "cluster", "observed_lower_bound": 2, "sum_upper_bound": 11}]


def test_sparse_frames_claim_only_bounds():
    frames = [_result("video-1", t, [[0.1, 0.1, 0.1, 0.1]] * n) for t, n in ((1.0, 3), (4.0, 5), (7.0, 2))]
    counts = summarize_counts(frames)["per_asset"][0]["counts"]["cluster"]
    assert counts["count_method"] == LOWER_BOUND_METHOD
    assert counts["confirmed_unique_count"] is None
    assert counts["observed_lower_bound"] == 5
    assert counts["sum_of_frame_counts_upper_bound"] == 10
    assert counts["coverage"] == "observed_frames_only"


def test_independent_photos_do_not_sum_into_a_count():
    photos = [_result(f"photo-{i}", None, [[0.1, 0.1, 0.1, 0.1]] * n) for i, n in enumerate((4, 6))]
    summary = summarize_counts(photos)
    assert summary["totals"] == [{"label": "cluster", "observed_lower_bound": 6, "sum_upper_bound": 10}]
    assert summary["extrapolation"] == "none"


def test_excluded_and_failed_frames_are_left_out():
    frames = [
        _result("video-1", 0.0, [[0.1, 0.1, 0.1, 0.1]]),
        _result("video-1", 0.2, [[0.1, 0.1, 0.1, 0.1]] * 9),
        detection.DetectionResult(status="failed", frame=detection.FrameRef(asset_id="video-1", frame_timestamp_seconds=0.4)),
    ]
    summary = summarize_counts(frames, excluded_frames={("video-1", 0.2)})
    assert summary["frames_excluded"] == 1
    assert summary["per_asset"][0]["frames"] == 1
    assert summary["totals"][0]["observed_lower_bound"] == 1


def test_track_label_respects_gap_and_label():
    frames = [[_det([0.1, 0.1, 0.2, 0.2])], [], [], [_det([0.1, 0.1, 0.2, 0.2])], [_det([0.1, 0.1, 0.2, 0.2], label="berry")]]
    tracks = track_label(frames, "cluster", max_gap=1)
    assert len(tracks) == 2  # the gap of two empty frames ends the first track
    assert all(track.hits == 1 for track in tracks)



# ---------------------------------------------------------------------------
# Server-side model registry (audit finding 5)
# ---------------------------------------------------------------------------

def test_registered_detector_is_verified_only_for_its_crops(monkeypatch):
    from app.services import crop_model_registry as registry

    monkeypatch.setattr(registry, "VERIFIED_DETECTORS", (registry.VerifiedDetector(
        model_id="rtdetr-grape-test", version="0.0-test", license="Apache-2.0 (verified)", weights_sha256="0" * 64,
        crop_ids=("wine_grape",), evaluation_id="eval-test",
    ),))
    grape = detection.parse_detector_response(_payload(), profile=GRAPE, frame=detection.FrameRef(), image=b"x", content_type="image/png")
    assert grape.model_verification == "registry_verified"
    assert grape.registered_model_license == "Apache-2.0 (verified)"
    almond = crop_profiles.get_profile("almond")
    other = detection.parse_detector_response(
        _payload(detections=[{"label": "nut", "score": 0.5, "box": [0.1, 0.1, 0.1, 0.1]}]),
        profile=almond, frame=detection.FrameRef(), image=b"x", content_type="image/png",
    )
    assert other.model_verification == "unregistered_unverified"  # registered for grapes only


def test_wrong_version_is_not_verified(monkeypatch):
    from app.services import crop_model_registry as registry

    monkeypatch.setattr(registry, "VERIFIED_DETECTORS", (registry.VerifiedDetector(
        model_id="rtdetr-grape-test", version="1.0", license="Apache-2.0", weights_sha256="0" * 64,
        crop_ids=("wine_grape",), evaluation_id="eval-test",
    ),))
    result = detection.parse_detector_response(_payload(), profile=GRAPE, frame=detection.FrameRef(), image=b"x", content_type="image/png")
    assert result.model_verification == "unregistered_unverified"


def test_registries_ship_empty():
    from app.services import crop_model_registry as registry

    assert registry.VERIFIED_DETECTORS == () and registry.VERIFIED_EVALUATIONS == ()



# ---------------------------------------------------------------------------
# Release controls: kill switch, canary allowlist, limits
# ---------------------------------------------------------------------------

def test_kill_switch_and_canary_allowlist(monkeypatch):
    monkeypatch.delenv("FIELD_DETECTION_ENABLED", raising=False)
    monkeypatch.setenv("FIELD_DETECTION_ORG_ALLOWLIST", "org-a")
    assert detection.detection_allowed_for("org-a") == (False, "detection_disabled")
    monkeypatch.setenv("FIELD_DETECTION_ENABLED", "true")
    assert detection.detection_allowed_for("org-a") == (True, "allowed")
    assert detection.detection_allowed_for("org-b") == (False, "organization_not_in_detection_canary")
    monkeypatch.setenv("FIELD_DETECTION_ORG_ALLOWLIST", "")
    assert detection.detection_allowed_for("org-a") == (False, "organization_not_in_detection_canary")  # empty = nobody


def test_detection_limits_are_bounded(monkeypatch):
    for name in ("FIELD_DETECTION_MAX_FRAMES_PER_OBSERVATION", "FIELD_DETECTION_OBSERVATION_BUDGET_SECONDS", "FIELD_DETECTION_DAILY_FRAME_BUDGET"):
        monkeypatch.delenv(name, raising=False)
    defaults = detection.detection_limits()
    assert (defaults.max_frames_per_observation, defaults.observation_budget_seconds, defaults.daily_frame_budget_per_organization) == (8, 60.0, 200)
    monkeypatch.setenv("FIELD_DETECTION_MAX_FRAMES_PER_OBSERVATION", "500")
    monkeypatch.setenv("FIELD_DETECTION_OBSERVATION_BUDGET_SECONDS", "nan")
    monkeypatch.setenv("FIELD_DETECTION_DAILY_FRAME_BUDGET", "not-a-number")
    limits = detection.detection_limits()
    assert limits.max_frames_per_observation == 8
    assert limits.observation_budget_seconds == 60.0
    assert limits.daily_frame_budget_per_organization == 200


@pytest.mark.parametrize(
    ("configured", "remaining", "expected"),
    [
        (30.0, None, {"connect": 5.0, "write": 5.0, "pool": 5.0, "read": 15.0}),   # setup phases capped at 5 s
        (30.0, 10.0, {"connect": 2.5, "write": 2.5, "pool": 2.5, "read": 2.5}),    # remaining budget wins
        (30.0, 2.0, {"connect": 0.5, "write": 0.5, "pool": 0.5, "read": 0.5}),
    ],
)
def test_bounded_timeout_phases_sum_to_the_frame_budget(configured, remaining, expected):
    """Second review: httpx applies timeouts per phase, so a single number allows up to 4x."""
    timeout = detection.bounded_timeout(configured, remaining)
    phases = {"connect": timeout.connect, "write": timeout.write, "pool": timeout.pool, "read": timeout.read}
    assert phases == pytest.approx(expected)
    assert sum(phases.values()) == pytest.approx(min(configured, remaining if remaining is not None else configured))


def test_http_provider_passes_the_bounded_timeout_per_frame():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json=_payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = detection.HttpDetectionProvider("https://detector.internal/infer", "k", client=client)
        provider.detect(b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef(), timeout_seconds=8.0)
    assert sum(seen[0].values()) == pytest.approx(8.0)
    assert seen[0]["read"] == pytest.approx(2.0)


def test_disabled_provider_accepts_a_frame_timeout():
    result = detection.DisabledDetectionProvider().detect(b"x", "image/png", GRAPE, detection.FrameRef(), timeout_seconds=3.0)
    assert result.status == "disabled"


def test_http_provider_streams_a_plain_body_with_its_length():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("content-length"), request.headers.get("transfer-encoding"), request.content))
        return httpx.Response(200, json=_payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = detection.HttpDetectionProvider("https://detector.internal/infer", "k", client=client).detect(
            b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef())
    length, transfer_encoding, content = seen[0]
    assert result.status == "ok"
    assert int(length) == len(content) and transfer_encoding is None
    assert json.loads(content)["crop_profile"] == GRAPE.crop_id


def test_http_provider_refuses_an_oversized_response():
    big = b"[" + b"0," * (detection.MAX_DETECTOR_RESPONSE_BYTES // 2) + b"0]"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=big))) as client:
        result = detection.HttpDetectionProvider("https://detector.internal/infer", "k", client=client).detect(
            b"x", "image/png", GRAPE, detection.FrameRef())
    assert result.status == "failed" and result.error == "detector_response_too_large" and not result.retryable


def test_http_provider_stops_uploading_once_the_frame_deadline_passes(monkeypatch):
    ticks = iter(range(0, 1000, 5))  # every clock read advances 5 s
    monkeypatch.setattr(detection, "_now", lambda: float(next(ticks)))
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_payload()))) as client:
        result = detection.HttpDetectionProvider("https://detector.internal/infer", "k", client=client).detect(
            b"x" * 1024, "image/png", GRAPE, detection.FrameRef(), timeout_seconds=3.0)
    assert result.status == "failed" and result.error == "detector_frame_time_budget_exceeded" and result.retryable


def test_a_trickling_detector_cannot_hold_a_frame_past_its_deadline():
    """Adversarial review: per-read timeouts never fire when bytes keep arriving."""
    import socketserver
    import threading
    import time as real_time
    from http.server import BaseHTTPRequestHandler

    class Trickle(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            try:
                for _ in range(40):  # 8 bytes every 0.15 s: each read finishes well inside its timeout
                    self.wfile.write(b"        ")
                    self.wfile.flush()
                    real_time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Trickle)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with httpx.Client(trust_env=False) as client:
            provider = detection.HttpDetectionProvider(f"http://127.0.0.1:{server.server_address[1]}/infer", "k", client=client)
            started = real_time.monotonic()
            result = provider.detect(b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef(), timeout_seconds=1.0)
            elapsed = real_time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
    assert result.status == "failed" and result.error == "detector_frame_time_budget_exceeded"
    assert elapsed < 1.5  # the caller gets the frame back at its 1 s deadline (with scheduling slack)


def _raw_detector(respond):
    """A local TCP detector whose response bytes and pacing the test controls."""
    import socketserver
    import threading

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            data = b""
            while b"\r\n\r\n" not in data:
                data += self.request.recv(65536)
            head, _, rest = data.partition(b"\r\n\r\n")
            length = int(next(line.split(b":")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")))
            while len(rest) < length:
                rest += self.request.recv(65536)
            try:
                respond(self.request)
            except OSError:
                pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize("attack", ["informational_flood", "trickled_headers", "trickled_trailers"])
def test_no_response_phase_can_hold_a_frame_past_its_deadline(attack):
    """Round-3 review: the deadline must also cover headers, 1xx responses and trailers."""
    import time as real_time

    body = json.dumps(_payload(detections=[{"label": "cluster", "score": 0.5, "box": [0.1, 0.1, 0.2, 0.2]}])).encode()

    def respond(sock):
        if attack == "informational_flood":
            for _ in range(40):
                sock.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                real_time.sleep(0.15)
        elif attack == "trickled_headers":
            for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 40:
                sock.sendall(bytes([byte]))
                real_time.sleep(0.15)
        else:  # the whole body at once, then trailers one byte at a time
            sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                         + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n")
            for byte in b"X-Trailer: " + b"a" * 40:
                sock.sendall(bytes([byte]))
                real_time.sleep(0.15)

    server = _raw_detector(respond)
    try:
        with httpx.Client(trust_env=False) as client:
            provider = detection.HttpDetectionProvider(f"http://127.0.0.1:{server.server_address[1]}/infer", "k", client=client)
            started = real_time.monotonic()
            result = provider.detect(b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef(), timeout_seconds=1.0)
            elapsed = real_time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
    assert result.status == "failed" and result.error == "detector_frame_time_budget_exceeded", (attack, result)
    assert elapsed < 1.5, (attack, elapsed)


def test_an_invalid_proxy_environment_is_a_typed_failure_not_a_crash(monkeypatch):
    """Building the client must stay inside the failure guard (round-3 review)."""
    monkeypatch.setenv("HTTPS_PROXY", "ftp://proxy.invalid:21")
    monkeypatch.setenv("HTTP_PROXY", "ftp://proxy.invalid:21")
    result = detection.HttpDetectionProvider("https://detector.internal/infer", "k").detect(
        b"\x89PNG\r\n\x1a\n", "image/png", GRAPE, detection.FrameRef(), timeout_seconds=2.0)
    assert result.status == "failed" and result.retryable

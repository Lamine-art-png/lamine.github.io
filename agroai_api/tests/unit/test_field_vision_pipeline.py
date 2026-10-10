"""Durable Field Intelligence pipeline: how visual analysis changes an observation.

The provider call is replaced with fixed responses; everything else (capture,
object storage, worker, extension, serialization) runs for real. These tests
pin that unstructured provider prose, invalid confidence, poor-quality frames,
and unsupported measurements cannot inflate an observation's severity or
confidence, and that each case is routed to human review with a reason.
"""
from __future__ import annotations

import io

import pytest

from app.models.field_intelligence import FieldObservationProcessingRun
from app.services import field_intelligence as svc
from app.services import field_vision as vision
from app.services.object_storage import S3ObjectStore
from tests.unit.test_field_intelligence import FakeStoreClient, _auth, _complete, _fetch, _initiate, _process

PNG = b"\x89PNG\r\n\x1a\n" + b"7" * 256


@pytest.fixture
def fake_store(monkeypatch):
    store = S3ObjectStore(bucket="agroai-test", prefix="agroai", client=FakeStoreClient())
    monkeypatch.setattr(svc, "get_object_store", lambda **_: store)
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    return store


def _provider_returns(monkeypatch, text: str, *, fallback: bool = False) -> None:
    def fake_analyze(_image, _content_type, _context):
        analysis = vision._bounded_analysis(vision._json_from_text(text))
        analysis["provider_fallback"] = fallback
        analysis["model_role"] = "fallback" if fallback else "primary"
        return vision.FieldVisionResult(
            provider="cloudflare_workers_ai", status="completed", model="vision-test", latency_ms=5, analysis=analysis,
        )

    monkeypatch.setattr(vision, "_analyze_one", fake_analyze)


def _photo_observation(client, db, headers, *, capture_id: str) -> dict:
    cap = _initiate(
        client, headers, client_capture_id=capture_id, idempotency_key=f"idem-{capture_id}",
        note_text="Walked rows four to six this morning.",
    ).json()["capture"]
    upload = client.post(
        f"/v1/field-intelligence/captures/{cap['id']}/assets",
        files={"file": ("row.png", io.BytesIO(PNG), "image/png")},
        data={"client_asset_id": f"photo-{capture_id}", "kind": "photo"}, headers=headers,
    )
    assert upload.status_code == 200, upload.text
    staged = _complete(client, headers, cap["id"]).json()["observation"]
    _process(db)
    return _fetch(client, headers, staged["id"])


def test_unstructured_provider_prose_cannot_escalate(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, "CRITICAL!!! Severe blight everywhere, 100% certain, spray immediately.")
    obs = _photo_observation(client, db, headers, capture_id="cap-prose")

    assert obs["structured"]["vision"]["analysis_state"] == "degraded"
    assert obs["structured"]["vision"]["confidence"] is None
    assert obs["severity"] not in {"high", "critical"}
    assert obs["status"] == "needs_review"
    assert "visual_analysis_unstructured_unverified" in obs["uncertain_fields"]
    assert "Unverified visual note" in (obs["summary"] or "")
    assert obs["provenance"]["vision_analysis_state"] == "degraded"
    assert obs["provenance"]["vision_confidence_kind"] == "model_self_reported_uncalibrated"
    # Unstructured prose must not become the recommended action either.
    assert "spray immediately" not in (obs["recommended_action"] or "")


def test_invalid_confidence_does_not_raise_observation_confidence(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Leaf spotting on two plants", "severity": "medium", "image_quality": "clear", "confidence": 9}')
    obs = _photo_observation(client, db, headers, capture_id="cap-conf")

    vision_result = obs["structured"]["vision"]
    assert vision_result["analysis_state"] == "structured"
    assert vision_result["confidence"] is None
    assert vision_result["confidence_summary"]["missing_or_invalid"] == 1
    # The old behaviour clamped 9 to 1.0 and lifted the observation to 0.85.
    assert (obs["confidence"] or 0.0) < 0.85
    vision_run = (
        db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs["id"])
        .filter(FieldObservationProcessingRun.stage == "vision")
        .order_by(FieldObservationProcessingRun.created_at.desc())
        .first()
    )
    assert vision_run is not None
    assert vision_run.output_json["confidence"] is None
    assert vision_run.output_json["confidence_kind"] == "model_self_reported_uncalibrated"
    assert "confidence_not_in_unit_interval" in vision_run.output_json["contract_violations"]


def test_poor_quality_critical_frame_is_reviewed_not_escalated(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Possible flooding, image very dark", "severity": "critical", "image_quality": "poor", "confidence": 0.4}')
    obs = _photo_observation(client, db, headers, capture_id="cap-poor")

    assert obs["structured"]["vision"]["severity"] == "low"
    assert obs["structured"]["vision"]["peak_severity"] == "critical"
    assert obs["severity"] not in {"high", "critical"}
    assert obs["status"] == "needs_review"
    assert "visual_severity_uncorroborated_single_frame" in obs["uncertain_fields"]


def test_fallback_model_frame_is_reviewed_not_escalated(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Burst lateral", "severity": "critical", "image_quality": "clear", "confidence": 0.9}', fallback=True)
    obs = _photo_observation(client, db, headers, capture_id="cap-fallback")

    assert obs["structured"]["vision"]["images_fallback_model"] == 1
    assert obs["severity"] not in {"high", "critical"}
    assert obs["status"] == "needs_review"


def test_unsupported_measurement_is_removed_and_flagged(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Chlorosis; residue about 0.3 ppm", "severity": "low", "image_quality": "clear", "confidence": 0.5, "recommended_follow_up": "Apply 2 L/ha of product."}')
    obs = _photo_observation(client, db, headers, capture_id="cap-chem")

    vision_result = obs["structured"]["vision"]
    assert vision_result["safety_flags"] == ["unsupported_quantitative_claim_removed"]
    assert "0.3 ppm" not in vision_result["summary"]
    assert "2 L/ha" not in (obs["recommended_action"] or "")
    assert "visual_unsupported_measurement_removed" in obs["uncertain_fields"]


def test_structured_high_severity_photo_still_escalates(client, db, fake_store, monkeypatch):
    """Trustworthy single-photo evidence keeps its severity (with review)."""
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Burst drip line spraying water", "visible_facts": [{"label": "Water spraying from drip line", "evidence": "visible jet", "confidence": 0.8}], "severity": "high", "image_quality": "clear", "confidence": 0.8}')
    obs = _photo_observation(client, db, headers, capture_id="cap-high")

    assert obs["structured"]["vision"]["severity"] == "high"
    assert obs["severity"] in {"high", "critical"}
    assert obs["status"] == "needs_review"
    assert obs["structured"]["vision"]["visible_facts"][0]["support_count"] == 1


# ---------------------------------------------------------------------------
# Specialized detection lane (feature-flagged)
# ---------------------------------------------------------------------------

def test_detection_flag_off_leaves_no_trace(client, db, fake_store, monkeypatch):
    monkeypatch.delenv("FIELD_DETECTION_ENABLED", raising=False)
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Rows", "severity": "low", "image_quality": "clear", "confidence": 0.5}')
    obs = _photo_observation(client, db, headers, capture_id="cap-det-off")
    assert "detections" not in obs["structured"]
    assert "detection_status" not in obs["provenance"]
    stages = {
        run.stage for run in db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs["id"]).all()
    }
    assert "detection" not in stages


def test_detection_flag_on_adds_reviewable_counts_without_escalating(client, db, fake_store, monkeypatch):
    from app.services import field_detection as detection
    from app.services import field_intelligence_vision_extension as extension

    class FakeDetector:
        name = "fake_detector"

        def detect(self, image, content_type, profile, frame):
            return detection.DetectionResult(
                status="ok", frame=frame, model_id="fake-almond-detector", model_version="test",
                detections=[detection.Detection(label="nut", score=0.7, box=[0.1 * i, 0.1, 0.05, 0.05]) for i in range(1, 6)],
            )

    monkeypatch.setenv("FIELD_DETECTION_ENABLED", "true")
    monkeypatch.setattr(extension, "get_detection_provider", lambda: FakeDetector())
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Nuts on lower limbs", "severity": "info", "image_quality": "clear", "confidence": 0.5}')
    obs = _photo_observation(client, db, headers, capture_id="cap-det-on")

    detections = obs["structured"]["detections"]
    assert detections["crop_profile"]["crop_id"] == "almond"  # resolved from "Almonds"
    assert detections["models"] == ["fake-almond-detector@test"]
    assert detections["review_status"] == "unreviewed"
    assert detections["validation_status"] == "unvalidated"
    assert detections["counts"]["totals"] == [{"label": "nut", "observed_lower_bound": 5, "sum_upper_bound": 5}]
    assert detections["counts"]["extrapolation"] == "none"
    assert obs["severity"] in {"info", "low"}
    assert obs["provenance"]["detection_status"] == "completed"
    run = (
        db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs["id"], FieldObservationProcessingRun.stage == "detection")
        .first()
    )
    assert run is not None and run.status == "completed" and run.model == "fake-almond-detector@test"


def test_detection_enabled_but_unconfigured_is_reported(client, db, fake_store, monkeypatch):
    monkeypatch.setenv("FIELD_DETECTION_ENABLED", "true")
    monkeypatch.delenv("FIELD_DETECTION_ENDPOINT", raising=False)
    monkeypatch.delenv("FIELD_DETECTION_API_KEY", raising=False)
    _, _, headers = _auth(db)
    _provider_returns(monkeypatch, '{"summary": "Rows", "severity": "low", "image_quality": "clear", "confidence": 0.5}')
    obs = _photo_observation(client, db, headers, capture_id="cap-det-misconfigured")
    assert "detections" not in obs["structured"]
    assert obs["provenance"]["detection_status"] == "not_run"
    assert obs["provenance"]["detection_reason"] == "detector_not_configured"

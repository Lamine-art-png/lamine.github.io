from __future__ import annotations

from app.services import field_vision as vision


def test_visual_output_is_bounded_and_never_upgrades_invalid_severity():
    result = vision._bounded_analysis(
        {
            "summary": "x" * 2000,
            "observations": ["visible leaf edge"] * 20,
            "possible_issue": "possible stress",
            "severity": "catastrophic",
            "confidence": 9,
            "recommended_follow_up": "inspect the affected row",
            "uncertainties": ["photo alone cannot confirm cause"] * 20,
        }
    )
    assert result["severity"] == "info"
    assert result["confidence"] == 1.0
    assert len(result["summary"]) == 1200
    assert len(result["observations"]) == 8
    assert len(result["uncertainties"]) == 8


def test_multiple_images_aggregate_with_human_review(monkeypatch):
    analyses = iter(
        [
            {
                "summary": "Brown edge visible.",
                "observations": ["Brown tissue at one leaf edge"],
                "possible_issue": "possible stress",
                "severity": "medium",
                "confidence": 0.6,
                "recommended_follow_up": "Inspect adjacent plants.",
                "uncertainties": ["Cause not confirmed"],
            },
            {
                "summary": "Emitter area appears wet.",
                "observations": ["Localized wet soil"],
                "possible_issue": "possible leak",
                "severity": "high",
                "confidence": 0.7,
                "recommended_follow_up": "Verify emitter flow and pressure.",
                "uncertainties": ["Flow cannot be measured from a photo"],
            },
        ]
    )

    def fake_analyze(_image, _content_type, _context):
        return vision.FieldVisionResult(
            provider="test",
            status="completed",
            model="vision-test",
            analysis=next(analyses),
        )

    monkeypatch.setattr(vision, "_analyze_one", fake_analyze)
    result = vision.analyze_field_images(
        [(b"image-a", "image/jpeg"), (b"image-b", "image/png")],
        {"field_name": "North 12", "crop": "almond"},
    )
    assert result.succeeded
    assert result.analysis["images_analyzed"] == 2
    assert result.analysis["severity"] == "high"
    assert result.analysis["human_review_required"] is True
    assert "possible leak" in result.analysis["possible_issues"]


def test_unconfigured_provider_is_truthful(monkeypatch):
    monkeypatch.setattr(vision, "_resolved_endpoint", lambda _model: "")
    monkeypatch.setattr(vision, "_resolved_key", lambda: "")
    result = vision._analyze_one(b"image", "image/jpeg", {})
    assert result.status == "unavailable"
    assert result.error == "vision_provider_not_configured"

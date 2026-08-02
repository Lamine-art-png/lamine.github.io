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
    assert len(result["summary"]) == 1600
    assert len(result["observations"]) == 12
    assert len(result["uncertainties"]) == 12
    assert result["possible_issues"] == ["possible stress"]
    assert result["verification_required"] is True


def test_multiple_images_aggregate_with_human_review(monkeypatch):
    analyses = iter(
        [
            {
                "summary": "Brown edge visible.",
                "visible_facts": [
                    {"label": "Brown tissue", "evidence": "one leaf edge", "confidence": 0.7}
                ],
                "hypotheses": [
                    {
                        "label": "possible stress",
                        "evidence": "brown leaf edge",
                        "confidence": 0.6,
                        "verification": "Inspect adjacent plants.",
                    }
                ],
                "observations": ["Brown tissue at one leaf edge"],
                "possible_issues": ["possible stress"],
                "crop_condition": "stressed",
                "coverage_assessment": "unknown",
                "equipment_condition": "not_visible",
                "severity": "medium",
                "confidence": 0.6,
                "recommended_follow_up": "Inspect adjacent plants.",
                "verification_required": True,
                "uncertainties": ["Cause not confirmed"],
            },
            {
                "summary": "Emitter area appears wet.",
                "visible_facts": [
                    {"label": "Localized wet soil", "evidence": "wet area near emitter", "confidence": 0.8}
                ],
                "hypotheses": [
                    {
                        "label": "possible leak",
                        "evidence": "localized wet soil",
                        "confidence": 0.7,
                        "verification": "Verify emitter flow and pressure.",
                    }
                ],
                "observations": ["Localized wet soil"],
                "possible_issues": ["possible leak"],
                "crop_condition": "unknown",
                "coverage_assessment": "uneven",
                "equipment_condition": "attention_needed",
                "severity": "high",
                "confidence": 0.7,
                "recommended_follow_up": "Verify emitter flow and pressure.",
                "verification_required": True,
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
    assert result.analysis["verification_required"] is True
    assert "possible leak" in result.analysis["possible_issues"]
    assert any(item["label"] == "Localized wet soil" for item in result.analysis["visible_facts"])
    assert any(item["label"] == "possible leak" for item in result.analysis["hypotheses"])


def test_unconfigured_provider_is_truthful(monkeypatch):
    monkeypatch.setattr(vision, "_resolved_endpoint", lambda _model: "")
    monkeypatch.setattr(vision, "_resolved_key", lambda: "")
    result = vision._analyze_one(b"image", "image/jpeg", {})
    assert result.status == "unavailable"
    assert result.error == "vision_provider_not_configured"

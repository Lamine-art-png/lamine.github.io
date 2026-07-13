from __future__ import annotations

import pytest


def _prospect(**overrides):
    from app.outreach.schemas import OutreachLanguage, OutreachMessageType, OutreachProspect, VerificationStatus

    values = {
        "prospect_id": "warm-pgim-001",
        "email": "buyer@example.com",
        "email_verification_status": VerificationStatus.verified_public_direct,
        "first_name": "Jason",
        "person_name": "Jason Example",
        "title": "Agricultural Investment Executive",
        "account": "Example Agricultural Investments",
        "country": "United States",
        "segment": "Institutional Farmland Owner / Asset Manager",
        "message_type": OutreachMessageType.warm_buyer_reengagement,
        "preferred_language": OutreachLanguage.en,
        "subject": "A concrete update since our irrigation discussion",
        "prior_relationship_context": (
            "When we last spoke, you challenged us to make the incremental value above your existing "
            "irrigation stack concrete and to reduce deployment risk for the operating team."
        ),
        "progress_since_last_contact": (
            "we replaced the earlier pilot-first premise with a live Enterprise Portal that teams can "
            "review directly before making a deployment commitment."
        ),
        "current_value_hypothesis": (
            "For your operation, the relevant value is a shared review layer across field evidence, "
            "priority exceptions, assigned actions, and verified outcomes—not another controller."
        ),
        "reengagement_ask": (
            "I would value your reaction to the portal and, if the operating view now addresses the "
            "questions you raised, a focused working session with the relevant operator."
        ),
    }
    values.update(overrides)
    return OutreachProspect(**values)


def test_warm_buyer_reengagement_requires_real_relationship_context():
    with pytest.raises(ValueError, match="prior_relationship_context"):
        _prospect(prior_relationship_context="too short")


def test_warm_buyer_reengagement_cannot_masquerade_as_signup_lifecycle():
    from app.outreach.schemas import VerificationStatus

    with pytest.raises(ValueError, match="cannot be used for buyer re-engagement"):
        _prospect(email_verification_status=VerificationStatus.first_party_signup)


def test_warm_buyer_reengagement_renders_relationship_aware_enterprise_email(monkeypatch):
    monkeypatch.setenv("OUTREACH_ENTERPRISE_PORTAL_URL", "https://portal.example.test")
    monkeypatch.setenv("OUTREACH_CALENDLY_URL", "https://meeting.example.test/30min")
    monkeypatch.setenv("OUTREACH_LAUNCH_VIDEO_URL", "https://video.example.test/watch")
    monkeypatch.setenv("OUTREACH_LAUNCH_VIDEO_THUMBNAIL_URL", "https://video.example.test/thumb.jpg")

    from app.outreach.config import OutreachSettings
    from app.outreach.templates import render_email

    settings = OutreachSettings.from_env()
    rendered = render_email(
        _prospect(),
        settings,
        unsubscribe_url="https://api.example.test/unsubscribe",
    )

    assert rendered.language == "en"
    assert rendered.localization_ready is True
    assert rendered.subject == "A concrete update since our irrigation discussion"
    assert "not as a cold introduction" in rendered.html
    assert "When we last spoke" in rendered.html
    assert "Since we last spoke" in rendered.html
    assert "live Enterprise Portal" in rendered.html
    assert "priority exceptions" in rendered.html
    assert "Review the AGRO-AI Enterprise Portal" in rendered.html
    assert "Book a focused working session with me" in rendered.html
    assert settings.enterprise_portal_url in rendered.html
    assert settings.calendly_url in rendered.html
    assert settings.launch_video_url in rendered.html
    assert settings.launch_video_thumbnail_url in rendered.html
    assert "We launched the AGRO-AI Enterprise Portal globally this week" not in rendered.html
    assert "I’m reaching out because" not in rendered.html
    assert "You are receiving this because we previously discussed AGRO-AI" in rendered.html


def test_warm_buyer_reengagement_is_blocked_from_automatic_non_english_delivery():
    from app.outreach.config import OutreachSettings
    from app.outreach.schemas import OutreachLanguage
    from app.outreach.templates import render_email

    rendered = render_email(
        _prospect(preferred_language=OutreachLanguage.es),
        OutreachSettings.from_env(),
        unsubscribe_url="https://api.example.test/unsubscribe",
    )

    assert rendered.language == "es"
    assert rendered.localization_ready is False

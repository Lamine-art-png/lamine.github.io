from __future__ import annotations

import importlib


def _cold_prospect():
    from app.outreach.schemas import OutreachLanguage, OutreachProspect, VerificationStatus

    return OutreachProspect(
        prospect_id="live-demo-cold-001",
        email="operator@example.com",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="Jordan",
        person_name="Jordan Example",
        title="Operations Director",
        account="Example Agricultural Operations",
        country="United States",
        segment="Enterprise Grower / Operator",
        preferred_language=OutreachLanguage.en,
        observation="the operating team coordinates field evidence across multiple systems",
        role_relevance="the role connects field execution and management review",
        pilot_wedge="connect field evidence, assigned actions and verified outcomes",
    )


def test_live_demo_defaults_are_hd_and_distinct_from_launch_video(monkeypatch):
    monkeypatch.delenv("OUTREACH_LIVE_DEMO_URL", raising=False)
    monkeypatch.delenv("OUTREACH_LIVE_DEMO_THUMBNAIL_URL", raising=False)

    from app.outreach.config import OutreachSettings

    settings = OutreachSettings.from_env()
    assert settings.launch_video_url == "https://youtu.be/NKVhX8imyT4"
    assert settings.launch_video_thumbnail_url == "https://i.ytimg.com/vi/NKVhX8imyT4/maxresdefault.jpg"
    assert settings.live_demo_url == "https://youtu.be/4KgH4R57tco"
    assert settings.live_demo_thumbnail_url == (
        "https://api.agroai-pilot.com/v1/outreach/assets/live-demo-thumbnail.jpg"
    )
    assert settings.live_demo_thumbnail_url != "https://i.ytimg.com/vi/4KgH4R57tco/maxresdefault.jpg"
    assert settings.live_demo_url != settings.launch_video_url


def test_cold_outreach_keeps_portal_and_launch_video_and_adds_live_demo():
    from app.outreach.config import OutreachSettings
    from app.outreach.templates import render_email

    settings = OutreachSettings.from_env()
    rendered = render_email(
        _cold_prospect(),
        settings,
        unsubscribe_url="https://api.example.test/u",
    )

    assert "Get started with AGRO-AI" in rendered.html
    assert "Watch a live demo" in rendered.html
    assert settings.live_demo_url in rendered.html
    assert settings.live_demo_thumbnail_url in rendered.html
    assert 'width="584" height="329"' in rendered.html
    assert "aspect-ratio:16/9" in rendered.html
    assert settings.launch_video_url in rendered.html
    assert settings.launch_video_thumbnail_url in rendered.html
    assert settings.live_demo_url in rendered.text
    assert settings.launch_video_url in rendered.text


def test_live_demo_is_a_first_party_tracked_destination():
    router_module = importlib.import_module("app.outreach.router")

    assert "live_demo" in router_module._TRACKED_LINK_KEYS
    assert router_module._tracking_destinations()["live_demo"] == router_module.settings.live_demo_url

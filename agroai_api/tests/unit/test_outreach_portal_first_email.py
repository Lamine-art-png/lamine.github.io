from __future__ import annotations

import html
import importlib
import re


def _settings():
    from app.outreach.config import OutreachSettings

    return OutreachSettings(
        resend_api_key="re_test",
        admin_token="admin",
        unsubscribe_secret="unsubscribe",
        sender="Lamine Dabo <lamine@mail.agroai-pilot.com>",
        reply_to="agroaicontact@gmail.com",
        public_api_base_url="https://api.agroai-pilot.com",
        website_url="https://agroai-pilot.com",
        enterprise_portal_url="https://app.agroai-pilot.com",
        calendly_url="https://calendly.com/agroaicontact/30min",
        launch_video_url="https://youtu.be/NKVhX8imyT4",
        launch_video_thumbnail_url="https://i.ytimg.com/vi/NKVhX8imyT4/maxresdefault.jpg",
        live_demo_url="https://youtu.be/4KgH4R57tco",
        live_demo_thumbnail_url="https://api.agroai-pilot.com/v1/outreach/assets/live-demo-thumbnail.jpg",
        company_address="AGRO-AI Inc., 524 Columbus Avenue, San Francisco, CA 94133, USA",
        dry_run=True,
        daily_send_limit=250,
        max_batch_size=25,
        resend_api_url="https://api.resend.com/emails",
    )


def _prospect():
    from app.outreach.schemas import OutreachProspect, VerificationStatus

    return OutreachProspect(
        prospect_id="portal-first-001",
        email="buyer@example.com",
        email_verification_status=VerificationStatus.verified_public_direct,
        first_name="Jordan",
        person_name="Jordan Example",
        title="Operations Director",
        account="Example Agricultural Operations",
        country="United States",
        segment="Groundwater Sustainability Agency / Water Agency",
        observation=(
            "the agency coordinates monitoring evidence, plan obligations, stakeholder input, "
            "and corrective work across technical and operating teams"
        ),
        role_relevance="the role connects decisions, ownership, reporting, and verified follow-through",
        pilot_wedge=(
            "connect one groundwater exception from source evidence through technical review, "
            "assigned response, stakeholder reporting, and verified closure"
        ),
        why_now="Implementation now depends on repeated measurement, reporting, and corrective action",
        subject="Example agency: one groundwater workflow worth reviewing",
    )


def test_production_router_uses_portal_first_renderer():
    router_module = importlib.import_module("app.outreach.router")
    assert router_module.render_email.__module__ == "app.outreach.templates_v2"


def test_portal_first_cold_email_has_clean_button_card_and_one_field_intelligence_sentence():
    from app.outreach.templates_v2 import render_email

    rendered = render_email(
        _prospect(),
        _settings(),
        unsubscribe_url="https://api.agroai-pilot.com/v1/outreach/unsubscribe?token=test",
    )

    assert "Open the Enterprise Portal" in rendered.html
    assert "View the Portal demo" in rendered.html
    assert "Book a workflow review" in rendered.html
    assert rendered.html.count("Field Intelligence") == 1
    assert rendered.html.count("Enterprise Portal") >= 3
    assert "Get started with AGRO-AI" not in rendered.html
    assert "Launch video" not in rendered.html
    assert "Watch a live demo" not in rendered.html
    assert rendered.html.count("href=") == 4  # three action buttons plus unsubscribe

    visible = html.unescape(re.sub(r"<[^>]+>", " ", rendered.html))
    visible = re.sub(r"\s+", " ", visible)
    assert "http://" not in visible
    assert "https://" not in visible


def test_portal_first_renderer_delegates_lifecycle_messages_to_legacy_template():
    from app.outreach.schemas import OutreachLanguage, OutreachMessageType, OutreachProspect, VerificationStatus
    from app.outreach.templates_v2 import render_email

    prospect = OutreachProspect(
        prospect_id="signup-001",
        email="buyer@example.com",
        email_verification_status=VerificationStatus.first_party_signup,
        first_name="Jordan",
        person_name="Jordan Example",
        title="Operations Director",
        account="Example Agricultural Operations",
        country="United States",
        segment="Post-signup executive follow-up",
        message_type=OutreachMessageType.post_signup_founder_followup,
        preferred_language=OutreachLanguage.en,
        subject="Thanks for signing up, Jordan",
        signup_interest_context="Your signup suggests a concrete interest in connecting field evidence and operating decisions.",
    )
    rendered = render_email(
        prospect,
        _settings(),
        unsubscribe_url="https://api.agroai-pilot.com/v1/outreach/unsubscribe?token=test",
    )
    assert "Thanks for creating an AGRO-AI workspace" in rendered.html
    assert "Open your AGRO-AI workspace" in rendered.html

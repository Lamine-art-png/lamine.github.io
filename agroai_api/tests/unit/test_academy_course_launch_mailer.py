"""Safeguards for the one-time Academy access notice."""
import os
import pytest

from app.services import academy_course_launch_mailer as campaign


def test_requires_exact_operator_activation(monkeypatch):
    monkeypatch.delenv("AGROAI_ACADEMY_A1_LAUNCH_SEND", raising=False)
    assert campaign.send_academy_launch_once() == {"not_enabled": 1}


def test_does_not_accept_unapproved_audit(monkeypatch):
    monkeypatch.setenv("AGROAI_ACADEMY_A1_LAUNCH_SEND", campaign.CAMPAIGN)
    monkeypatch.setenv("AGROAI_ACADEMY_A1_LAUNCH_BCC", "contact@agroai-pilot.com")
    assert campaign.send_academy_launch_once() == {"blocked": 1}


def test_email_and_opt_in_filtering():
    assert campaign._email("  EXAMPLE@Example.COM ") == "example@example.com"
    assert campaign._email("bad@email") == ""
    assert campaign._consent({"email_opt_in": True}) is True
    assert campaign._consent({"email_opt_in": "true"}) is True
    assert campaign._consent({"email_opt_in": False}) is False
    assert campaign._consent({}) is False


def test_html_personalization_is_escaped():
    h, t = campaign._render("Zoë <admin>", "Hello {{first_name}}", "Hello {{first_name}}")
    assert h.startswith("Hello Zoë") and "<admin>" not in h
    assert t.startswith("Hello Zoë")


def test_launch_email_uses_official_email_safe_png_logo():
    # The Academy brand system deliberately generates email-lockup.png with an
    # opaque white background. Avoid transparent WebP: Gmail's image proxy and
    # email clients can distort or misrender that version.
    from pathlib import Path

    html_template = (
        Path(__file__).resolve().parents[2]
        / "app" / "email_templates" / "academy_launch_20261029.html"
    ).read_text(encoding="utf-8")
    assert 'src="https://academy.agroai-pilot.com/static/brand/email-lockup.png"' in html_template
    assert 'brand/academy-lockup-h-light.webp' not in html_template
    assert 'padding:24px 32px 22px;background:#ffffff' in html_template
    assert html_template.index("brand/email-lockup.png") < html_template.index("THE ACADEMY IS OPEN")

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

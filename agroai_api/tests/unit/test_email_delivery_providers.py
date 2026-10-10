"""Provider-level contract: every email provider delivers List-Unsubscribe headers.

Lifecycle email passes List-Unsubscribe / List-Unsubscribe-Post (RFC 8058) to
``send_email``; each configured provider (SMTP, Resend, SendGrid) must put them
on the outgoing message. Transactional sends pass no headers and must be
unchanged.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import email_delivery

UNSUBSCRIBE = {
    "List-Unsubscribe": "<https://api.example.test/v1/email/lifecycle/unsubscribe?u=u1&t=tok>",
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
}
TAGS = [{"name": "category", "value": "lifecycle"}, {"name": "step", "value": "welcome"}]


@pytest.fixture
def provider(monkeypatch):
    def configure(name: str) -> None:
        for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "RESEND_API_KEY", "SENDGRID_API_KEY"):
            monkeypatch.setattr(settings, key, None, raising=False)
        monkeypatch.setattr(settings, "FROM_EMAIL", "AGRO-AI <hello@agroai-pilot.com>", raising=False)
        if name == "smtp":
            monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test", raising=False)
            monkeypatch.setattr(settings, "SMTP_USERNAME", "user", raising=False)
            monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass", raising=False)
        elif name == "resend":
            monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test", raising=False)
        elif name == "sendgrid":
            monkeypatch.setattr(settings, "SENDGRID_API_KEY", "SG.test", raising=False)
        assert email_delivery.delivery_status()["provider"] == name

    return configure


class _Response:
    status_code = 202
    text = '{"id":"msg_1"}'


@pytest.fixture
def http_capture(monkeypatch):
    sent: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None):
            sent.append({"url": url, "json": json, "client": self.kwargs})
            return _Response()

    monkeypatch.setattr(email_delivery.httpx, "Client", Client)
    return sent


@pytest.fixture
def smtp_capture(monkeypatch):
    sent: list = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", SMTP)
    return sent


def _send(**extra):
    return email_delivery.send_email(to_email="grower@example.test", subject="Hello", text_body="Body", html_body="<p>Body</p>", **extra)


def test_sendgrid_receives_list_unsubscribe_headers(provider, http_capture):
    provider("sendgrid")
    result = _send(headers=UNSUBSCRIBE, tags=TAGS)
    assert result["ok"] is True and result["provider"] == "sendgrid"
    (request,) = http_capture
    assert request["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert request["json"]["headers"] == UNSUBSCRIBE
    assert request["json"]["custom_args"] == {"category": "lifecycle", "step": "welcome"}


def test_resend_receives_list_unsubscribe_headers(provider, http_capture):
    provider("resend")
    result = _send(headers=UNSUBSCRIBE, tags=TAGS)
    assert result["ok"] is True and result["provider"] == "resend"
    (request,) = http_capture
    assert request["url"] == "https://api.resend.com/emails"
    assert request["json"]["headers"] == UNSUBSCRIBE
    assert request["json"]["tags"] == TAGS


def test_smtp_message_carries_list_unsubscribe_headers(provider, smtp_capture):
    provider("smtp")
    result = _send(headers=UNSUBSCRIBE, tags=TAGS)
    assert result["ok"] is True and result["provider"] == "smtp"
    (message,) = smtp_capture
    assert message["List-Unsubscribe"] == UNSUBSCRIBE["List-Unsubscribe"]
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@pytest.mark.parametrize("name", ["sendgrid", "resend"])
def test_transactional_http_payload_has_no_list_headers(provider, http_capture, name):
    provider(name)
    assert _send()["ok"] is True
    (request,) = http_capture
    assert "headers" not in request["json"]
    assert "tags" not in request["json"] and "custom_args" not in request["json"]
    assert request["json"]["subject"] == "Hello"


def test_transactional_smtp_message_has_no_list_headers(provider, smtp_capture):
    provider("smtp")
    assert _send()["ok"] is True
    (message,) = smtp_capture
    assert message["List-Unsubscribe"] is None and message["List-Unsubscribe-Post"] is None


@pytest.mark.parametrize("name", ["sendgrid", "resend"])
def test_welcome_audit_bcc_uses_hidden_provider_recipients(provider, http_capture, name):
    provider(name)
    result = _send(bcc_email="contact@agroai-pilot.com")
    assert result["ok"] is True
    payload = http_capture[0]["json"]
    assert "Bcc" not in payload.get("headers", {})
    if name == "resend":
        assert payload["to"] == ["grower@example.test"]
        assert payload["bcc"] == ["contact@agroai-pilot.com"]
    else:
        recipients = payload["personalizations"][0]
        assert recipients["to"] == [{"email": "grower@example.test"}]
        assert recipients["bcc"] == [{"email": "contact@agroai-pilot.com"}]


def test_welcome_audit_bcc_smtp(provider, smtp_capture):
    provider("smtp")
    result = _send(bcc_email="contact@agroai-pilot.com")
    assert result["ok"] is True
    (message,) = smtp_capture
    assert message["To"] == "grower@example.test"
    assert message["Bcc"] == "contact@agroai-pilot.com"

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from urllib import request

from app.core.config import settings


def delivery_status() -> dict:
    smtp_ready = all([settings.SMTP_HOST, settings.SMTP_USERNAME, settings.SMTP_PASSWORD, settings.FROM_EMAIL])
    resend_ready = bool(settings.RESEND_API_KEY and settings.FROM_EMAIL)
    sendgrid_ready = bool(settings.SENDGRID_API_KEY and settings.FROM_EMAIL)
    configured = smtp_ready or resend_ready or sendgrid_ready
    missing = []
    if not settings.FROM_EMAIL:
        missing.append("FROM_EMAIL")
    if not configured:
        if not settings.RESEND_API_KEY:
            missing.append("RESEND_API_KEY")
        if not settings.SENDGRID_API_KEY:
            missing.append("SENDGRID_API_KEY")
        if not settings.SMTP_HOST:
            missing.append("SMTP_HOST")
    return {
        "configured": configured,
        "provider": "smtp" if smtp_ready else "resend" if resend_ready else "sendgrid" if sendgrid_ready else "none",
        "missing_env": sorted(set(missing)),
    }


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    status = delivery_status()
    if not status["configured"]:
        return False
    provider = status["provider"]
    if provider == "smtp":
        return _send_smtp(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
    if provider == "resend":
        return _send_resend(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
    if provider == "sendgrid":
        return _send_sendgrid(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
    return False


def _send_smtp(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.FROM_EMAIL
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
    return True


def _send_resend(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    payload = json.dumps(
        {
            "from": settings.FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
            "html": html_body or f"<p>{text_body}</p>",
        }
    ).encode()
    req = request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=15) as response:
        return 200 <= response.status < 300


def _send_sendgrid(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    payload = json.dumps(
        {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": settings.FROM_EMAIL},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body or f"<p>{text_body}</p>"},
            ],
        }
    ).encode()
    req = request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=15) as response:
        return 200 <= response.status < 300

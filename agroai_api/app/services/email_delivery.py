from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from urllib import error, request

from app.core.config import settings

logger = logging.getLogger(__name__)


def _configured_from_email() -> str:
    return (settings.FROM_EMAIL or "").strip()


def _from_address() -> str:
    return parseaddr(_configured_from_email())[1] or _configured_from_email()


def _from_domain() -> str:
    address = _from_address()
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _verification_base_url() -> str:
    return (settings.RESEND_APP_URL or settings.APP_URL or "https://app.agroai-pilot.com").strip().rstrip("/")


def _safe_provider_response(value: str | None) -> str | None:
    if not value:
        return None
    # Provider errors do not include our API key, but keep the response capped so
    # operational diagnostics can be surfaced safely in the portal console.
    return value.replace(settings.RESEND_API_KEY, "[redacted]")[:1000] if settings.RESEND_API_KEY else value[:1000]


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
    provider = "smtp" if smtp_ready else "resend" if resend_ready else "sendgrid" if sendgrid_ready else "none"
    return {
        "configured": configured,
        "provider": provider,
        "missing_env": sorted(set(missing)),
        "from_email_configured": bool(settings.FROM_EMAIL),
        "from_email_domain": _from_domain(),
        "from_address": _from_address(),
        "resend_configured": bool(settings.RESEND_API_KEY),
        "sendgrid_configured": bool(settings.SENDGRID_API_KEY),
        "smtp_configured": smtp_ready,
        "resend_app_url_configured": bool(settings.RESEND_APP_URL),
        "verification_base_url": _verification_base_url(),
    }


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    """Send one email and return a safe operational result.

    Auth and onboarding flows must never claim an email was sent unless the
    provider accepted it. The returned provider response is capped and redacted.
    """

    status = delivery_status()
    if not status["configured"]:
        logger.warning("Email delivery not configured: missing=%s", status["missing_env"])
        return {
            "ok": False,
            "provider": "none",
            "reason": "email_provider_not_configured",
            "status": status,
        }

    provider = status["provider"]
    logger.info("Sending email through %s to=%s from=%s", provider, to_email, status.get("from_address"))
    try:
        if provider == "smtp":
            return _send_smtp(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
        if provider == "resend":
            return _send_resend(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
        if provider == "sendgrid":
            return _send_sendgrid(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body)
    except Exception as exc:  # pragma: no cover - production network/provider path
        logger.exception("Email delivery failed before provider response provider=%s", provider)
        return {"ok": False, "provider": provider, "reason": exc.__class__.__name__}

    return {"ok": False, "provider": provider, "reason": "unsupported_provider"}


def _send_smtp(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
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
    logger.info("SMTP email accepted to=%s", to_email)
    return {"ok": True, "provider": "smtp", "status_code": 250, "reason": "accepted"}


def _send_resend(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    from_address = _from_address()
    payload = json.dumps(
        {
            # Use the raw verified sender address instead of a display-name string.
            # This removes one common source of provider-side 403 validation errors
            # while keeping the AGRO-AI branding inside the email template itself.
            "from": from_address,
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
    try:
        with request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            ok = 200 <= response.status < 300
            logger.info("Resend email response status=%s body=%s", response.status, body[:500])
            return {
                "ok": ok,
                "provider": "resend",
                "status_code": response.status,
                "reason": "accepted" if ok else "provider_rejected",
                "provider_response": _safe_provider_response(body),
                "from_address": from_address,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Resend email failed status=%s body=%s", exc.code, body[:1000])
        return {
            "ok": False,
            "provider": "resend",
            "status_code": exc.code,
            "reason": "provider_rejected",
            "provider_response": _safe_provider_response(body),
            "from_address": from_address,
        }
    except Exception as exc:
        logger.exception("Resend email delivery failed before response")
        return {"ok": False, "provider": "resend", "reason": exc.__class__.__name__, "from_address": from_address}


def _send_sendgrid(*, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    from_address = _from_address()
    payload = json.dumps(
        {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_address, "name": "AGRO-AI"},
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
    try:
        with request.urlopen(req, timeout=15) as response:
            ok = 200 <= response.status < 300
            logger.info("SendGrid email response status=%s", response.status)
            return {"ok": ok, "provider": "sendgrid", "status_code": response.status, "reason": "accepted" if ok else "provider_rejected"}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("SendGrid email failed status=%s body=%s", exc.code, body[:1000])
        return {"ok": False, "provider": "sendgrid", "status_code": exc.code, "reason": "provider_rejected", "provider_response": _safe_provider_response(body)}

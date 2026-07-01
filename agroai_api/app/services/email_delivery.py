from __future__ import annotations

import base64
import json
import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

import httpx

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
    if settings.RESEND_API_KEY:
        value = value.replace(settings.RESEND_API_KEY, "[redacted]")
    if settings.SENDGRID_API_KEY:
        value = value.replace(settings.SENDGRID_API_KEY, "[redacted]")
    return value[:1000]


def _provider_rejection_reason(body: str | None) -> str:
    body = body or ""
    try:
        parsed = json.loads(body)
        message = parsed.get("message") or parsed.get("error") or parsed.get("name")
        if message:
            safe = str(message).strip().replace("\n", " ")[:220]
            return f"provider_rejected: {safe}"
    except Exception:
        pass
    safe_body = body.strip().replace("\n", " ")[:220]
    return f"provider_rejected: {safe_body}" if safe_body else "provider_rejected"


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


def _normalize_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in attachments or []:
        filename = str(item.get("filename") or "attachment.bin").strip()[:160]
        content_type = str(item.get("content_type") or "application/octet-stream").strip()
        data = item.get("data") or item.get("content") or b""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not isinstance(data, bytes) or not data:
            continue
        normalized.append({"filename": filename, "content_type": content_type, "data": data})
    return normalized


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str | None = None, attachments: list[dict[str, Any]] | None = None) -> dict:
    """Send one email and return a safe operational result."""

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
    safe_attachments = _normalize_attachments(attachments)
    logger.info("Sending email through %s to=%s from=%s attachments=%s", provider, to_email, status.get("from_address"), len(safe_attachments))
    try:
        if provider == "smtp":
            return _send_smtp(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body, attachments=safe_attachments)
        if provider == "resend":
            return _send_resend(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body, attachments=safe_attachments)
        if provider == "sendgrid":
            return _send_sendgrid(to_email=to_email, subject=subject, text_body=text_body, html_body=html_body, attachments=safe_attachments)
    except Exception as exc:  # pragma: no cover - production network/provider path
        logger.exception("Email delivery failed before provider response provider=%s", provider)
        return {"ok": False, "provider": provider, "reason": exc.__class__.__name__}

    return {"ok": False, "provider": provider, "reason": "unsupported_provider"}


def _split_content_type(value: str) -> tuple[str, str]:
    if "/" not in value:
        return "application", "octet-stream"
    maintype, subtype = value.split("/", 1)
    return maintype or "application", subtype or "octet-stream"


def _send_smtp(*, to_email: str, subject: str, text_body: str, html_body: str | None = None, attachments: list[dict[str, Any]] | None = None) -> dict:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.FROM_EMAIL
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for attachment in attachments or []:
        maintype, subtype = _split_content_type(attachment["content_type"])
        message.add_attachment(
            attachment["data"],
            maintype=maintype,
            subtype=subtype,
            filename=attachment["filename"],
        )
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)
    logger.info("SMTP email accepted to=%s", to_email)
    return {"ok": True, "provider": "smtp", "status_code": 250, "reason": "accepted", "attachments": len(attachments or [])}


def _resend_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    return [
        {
            "filename": item["filename"],
            "content": base64.b64encode(item["data"]).decode("ascii"),
        }
        for item in attachments or []
    ]


def _send_resend(*, to_email: str, subject: str, text_body: str, html_body: str | None = None, attachments: list[dict[str, Any]] | None = None) -> dict:
    from_address = _from_address()
    payload: dict[str, Any] = {
        "from": from_address,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body or f"<p>{text_body}</p>",
    }
    safe_attachments = _resend_attachments(attachments)
    if safe_attachments:
        payload["attachments"] = safe_attachments
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "agro-ai-api/2.0 (+https://app.agroai-pilot.com)",
    }
    try:
        with httpx.Client(timeout=30, headers=headers, follow_redirects=False) as client:
            response = client.post("https://api.resend.com/emails", json=payload)
        body = response.text
        ok = 200 <= response.status_code < 300
        if ok:
            logger.info("Resend email response status=%s body=%s", response.status_code, body[:500])
            return {
                "ok": True,
                "provider": "resend",
                "status_code": response.status_code,
                "reason": "accepted",
                "provider_response": _safe_provider_response(body),
                "from_address": from_address,
                "attachments": len(safe_attachments),
            }
        logger.error("Resend email failed status=%s body=%s", response.status_code, body[:1000])
        return {
            "ok": False,
            "provider": "resend",
            "status_code": response.status_code,
            "reason": _provider_rejection_reason(body),
            "provider_response": _safe_provider_response(body),
            "from_address": from_address,
        }
    except httpx.HTTPError as exc:
        logger.exception("Resend email delivery failed before provider response")
        return {"ok": False, "provider": "resend", "reason": exc.__class__.__name__, "from_address": from_address}


def _sendgrid_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    return [
        {
            "content": base64.b64encode(item["data"]).decode("ascii"),
            "filename": item["filename"],
            "type": item["content_type"],
            "disposition": "attachment",
        }
        for item in attachments or []
    ]


def _send_sendgrid(*, to_email: str, subject: str, text_body: str, html_body: str | None = None, attachments: list[dict[str, Any]] | None = None) -> dict:
    from_address = _from_address()
    payload: dict[str, Any] = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_address, "name": "AGRO-AI"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body or f"<p>{text_body}</p>"},
        ],
    }
    safe_attachments = _sendgrid_attachments(attachments)
    if safe_attachments:
        payload["attachments"] = safe_attachments
    headers = {"Authorization": f"Bearer {settings.SENDGRID_API_KEY}", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            response = client.post("https://api.sendgrid.com/v3/mail/send", json=payload)
        body = response.text
        ok = 200 <= response.status_code < 300
        if ok:
            logger.info("SendGrid email response status=%s", response.status_code)
            return {"ok": True, "provider": "sendgrid", "status_code": response.status_code, "reason": "accepted", "attachments": len(safe_attachments)}
        logger.error("SendGrid email failed status=%s body=%s", response.status_code, body[:1000])
        return {"ok": False, "provider": "sendgrid", "status_code": response.status_code, "reason": _provider_rejection_reason(body), "provider_response": _safe_provider_response(body)}
    except httpx.HTTPError as exc:
        logger.exception("SendGrid email delivery failed before provider response")
        return {"ok": False, "provider": "sendgrid", "reason": exc.__class__.__name__}

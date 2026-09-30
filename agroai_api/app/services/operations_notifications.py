"""Deliver stored customer requests to the AGRO-AI operations inbox.

Requests are always stored first (durability); this module then emails the
operations inbox and records the real outcome on the request so a failed or
unconfigured delivery is visible instead of silently lost.
"""
from __future__ import annotations

import logging
from html import escape

from app.core.config import settings
from app.models.saas import SaaSRequest
from app.services.email_delivery import send_email

logger = logging.getLogger("agroai.operations_notifications")

DEFAULT_OPERATIONS_EMAIL = "contact@agroai-pilot.com"


def operations_inbox() -> str:
    return (getattr(settings, "SUPPORT_EMAIL", "") or DEFAULT_OPERATIONS_EMAIL).strip()


def _field(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    return text or "Not provided"


def notify_operations(row: SaaSRequest, *, organization_name: str | None = None) -> str:
    """Email the request to operations and persist the outcome on ``row``.

    Returns the notification status. The caller commits.
    """
    fields = [
        ("Request ID", row.id),
        ("Type", row.type),
        ("Priority", row.priority),
        ("Organization", organization_name or row.company),
        ("Organization ID", row.organization_id),
        ("Workspace ID", row.workspace_id),
        ("Name", row.name),
        ("Email", row.email),
        ("Role", row.role),
        ("Source page", row.source_page),
    ]
    subject = f"AGRO-AI {row.type} request: {_field(row.subject)[:150]}"
    text_body = "\n".join(f"{label}: {_field(value)}" for label, value in fields) + f"\n\n{_field(row.message)}"
    html_rows = "".join(f"<p><strong>{escape(label)}:</strong> {escape(_field(value))}</p>" for label, value in fields)
    html_body = f"<h2>{escape(subject)}</h2>{html_rows}<p style=\"white-space:pre-wrap\">{escape(_field(row.message))}</p>"
    try:
        result = send_email(to_email=operations_inbox(), subject=subject, text_body=text_body, html_body=html_body)
    except Exception as exc:  # pragma: no cover - send_email already contains provider errors
        result = {"ok": False, "reason": exc.__class__.__name__}
    if result.get("ok"):
        row.notification_status = "emailed"
        logger.info("operations_request.provider_accepted request_id=%s type=%s", row.id, row.type)
    elif result.get("reason") == "email_provider_not_configured":
        row.notification_status = "email_not_configured"
        logger.error("operations_request.not_delivered request_id=%s reason=email_provider_not_configured", row.id)
    else:
        row.notification_status = f"email_failed:{str(result.get('reason') or 'unknown')[:180]}"
        logger.error("operations_request.provider_rejected request_id=%s reason=%s", row.id, result.get("reason"))
    return row.notification_status

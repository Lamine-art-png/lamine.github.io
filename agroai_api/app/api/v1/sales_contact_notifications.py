from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.services.email_delivery import delivery_status, send_email

from .product_shell import SaaSRequestPayload, _create_saas_request

router = APIRouter(tags=["sales"])

CONTACT_NOTIFICATION_EMAIL = "contact@agroai-pilot.com"


def _display(value: object | None) -> str:
    text = str(value).strip() if value is not None else ""
    return text or "Not provided"


def _html(value: object | None) -> str:
    return escape(_display(value), quote=True)


@router.post("/sales/contact")
def sales_contact(payload: SaaSRequestPayload, db: Session = Depends(get_db)) -> dict:
    """Store every sales inquiry and notify the current AGRO-AI inbox.

    Storage remains the source of truth. A provider outage cannot erase the
    submission; the notification status records whether delivery succeeded.
    """

    row = _create_saas_request(
        db,
        request_type="sales",
        subject=payload.subject,
        message=payload.message,
        priority=payload.priority,
        name=payload.name,
        email=payload.email,
        company=payload.company,
        role=payload.role,
        source_page=payload.source_page or "pricing",
        metadata=payload.metadata,
    )

    delivery = delivery_status()
    if delivery.get("configured"):
        result = send_email(
            to_email=CONTACT_NOTIFICATION_EMAIL,
            subject=f"AGRO-AI demo request: {payload.subject}",
            text_body=(
                f"Request ID: {row.id}\n"
                f"Source: {_display(payload.source_page or 'pricing')}\n"
                f"Priority: {_display(payload.priority)}\n"
                f"Name: {_display(payload.name)}\n"
                f"Email: {_display(payload.email)}\n"
                f"Company: {_display(payload.company)}\n"
                f"Role: {_display(payload.role)}\n\n"
                f"Subject: {_display(payload.subject)}\n\n"
                f"{_display(payload.message)}"
            ),
            html_body=(
                "<h2>New AGRO-AI demo or sales request</h2>"
                f"<p><strong>Request ID:</strong> {_html(row.id)}</p>"
                f"<p><strong>Source:</strong> {_html(payload.source_page or 'pricing')}</p>"
                f"<p><strong>Priority:</strong> {_html(payload.priority)}</p>"
                f"<p><strong>Name:</strong> {_html(payload.name)}</p>"
                f"<p><strong>Email:</strong> {_html(payload.email)}</p>"
                f"<p><strong>Company:</strong> {_html(payload.company)}</p>"
                f"<p><strong>Role:</strong> {_html(payload.role)}</p>"
                f"<p><strong>Subject:</strong> {_html(payload.subject)}</p>"
                f"<p>{_html(payload.message).replace(chr(10), '<br>')}</p>"
            ),
        )
        row.notification_status = (
            "emailed:contact@agroai-pilot.com"
            if result.get("ok")
            else f"email_failed:{result.get('reason') or 'unknown'}"
        )
    else:
        row.notification_status = "stored_email_not_configured"

    db.commit()
    return {
        "status": "received",
        "message": "Sales request received.",
        "request_id": row.id,
        "notification_status": row.notification_status,
    }

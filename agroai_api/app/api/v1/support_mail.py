from __future__ import annotations

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.saas import SaaSRequest
from app.services.email_delivery import delivery_status, send_email

router = APIRouter(tags=["support-mail"])


class SupportIntakePayload(BaseModel):
    category: str = Field(default="support", max_length=80)
    subject: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=4000)
    name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=240)
    company: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=120)
    workspace_id: str | None = None
    source_page: str | None = Field(default="support", max_length=160)


def _request_type(category: str) -> str:
    clean = (category or "support").strip().lower()
    return "bug" if clean == "issue" else clean if clean in {"support", "integration", "onboarding", "sales", "bug"} else "support"


def _recipient() -> str:
    return (getattr(settings, "SUPPORT_EMAIL", "") or settings.FROM_EMAIL or "dabolamine2000@yahoo.com").strip()


@router.post("/support/ticket-public")
def support_ticket_public(payload: SupportIntakePayload = Body(...)) -> dict:
    db: Session = SessionLocal()
    try:
        row = SaaSRequest(
            organization_id=None,
            workspace_id=payload.workspace_id,
            user_id=None,
            type=_request_type(payload.category),
            status="received",
            priority="medium",
            name=payload.name,
            email=payload.email,
            company=payload.company,
            role=payload.role,
            subject=payload.subject,
            message=payload.message,
            source_page=payload.source_page or "support",
            notification_status="stored",
            metadata_json={"intake": "support_ticket_public"},
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        delivery = delivery_status()
        recipient = _recipient()
        if delivery.get("configured") and recipient:
            result = send_email(
                to_email=recipient,
                subject=f"AGRO-AI support request: {payload.subject}",
                text_body=(
                    f"Request ID: {row.id}\n"
                    f"Type: {row.type}\n"
                    f"Name: {payload.name or 'Not provided'}\n"
                    f"Email: {payload.email or 'Not provided'}\n"
                    f"Company: {payload.company or 'Not provided'}\n"
                    f"Workspace: {payload.workspace_id or 'Not provided'}\n\n"
                    f"{payload.message}"
                ),
                html_body=(
                    f"<h2>AGRO-AI support request</h2>"
                    f"<p><strong>Request ID:</strong> {row.id}</p>"
                    f"<p><strong>Type:</strong> {row.type}</p>"
                    f"<p><strong>Name:</strong> {payload.name or 'Not provided'}</p>"
                    f"<p><strong>Email:</strong> {payload.email or 'Not provided'}</p>"
                    f"<p><strong>Company:</strong> {payload.company or 'Not provided'}</p>"
                    f"<p><strong>Workspace:</strong> {payload.workspace_id or 'Not provided'}</p>"
                    f"<p>{payload.message}</p>"
                ),
            )
            row.notification_status = "emailed" if result.get("ok") else f"email_failed:{result.get('reason') or 'unknown'}"
        else:
            row.notification_status = "stored_email_not_configured"
        db.commit()
        return {"status": "received", "message": "Thanks - your request was received.", "request_id": row.id, "notification_status": row.notification_status}
    finally:
        db.close()

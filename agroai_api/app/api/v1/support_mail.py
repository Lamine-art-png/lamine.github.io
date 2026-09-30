from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.rate_limiting import limiter
from app.db.base import get_db
from app.models.saas import SaaSRequest
from app.services.operations_notifications import notify_operations

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


@router.post("/support/ticket-public")
@limiter.limit("5/minute")
def support_ticket_public(request: Request, payload: SupportIntakePayload = Body(...), db: Session = Depends(get_db)) -> dict:
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
    db.commit()  # durable before any delivery attempt
    db.refresh(row)
    notify_operations(row)
    db.commit()
    return {"status": "received", "message": "Thanks - your request was received.", "request_id": row.id, "notification_status": row.notification_status}

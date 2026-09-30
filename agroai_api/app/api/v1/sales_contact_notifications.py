from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_db

from .product_shell import SaaSRequestPayload, _create_saas_request

router = APIRouter(tags=["sales"])


@router.post("/sales/contact")
def sales_contact(payload: SaaSRequestPayload, db: Session = Depends(get_db)) -> dict:
    """Store every sales inquiry and notify the AGRO-AI operations inbox.

    ``_create_saas_request`` stores the row first and then emails operations;
    the notification status records whether delivery succeeded.
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

    return {
        "status": "received",
        "message": "Sales request received.",
        "request_id": row.id,
        "notification_status": row.notification_status,
    }

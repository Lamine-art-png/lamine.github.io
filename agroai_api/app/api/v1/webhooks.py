"""Webhook management endpoints."""
import logging
import uuid
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_tenant_id
from app.schemas.webhook import (
    RegisterWebhookRequest,
    RegisterWebhookResponse,
    TestWebhookResponse,
)
from app.models.webhook import Webhook
from app.services.webhook import WebhookService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/webhooks",
    response_model=RegisterWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_webhook(
    request: RegisterWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """
    Register webhook endpoint.

    Subscribes to specified event types:
    - recommendation.created
    - irrigation.started
    - irrigation.completed
    - alarm.triggered
    - *  (all events)
    """
    webhook = Webhook(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        url=str(request.url),
        event_types=request.event_types,
        secret=request.secret,
        active=True,
    )

    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    return RegisterWebhookResponse(
        id=webhook.id,
        url=webhook.url,
        event_types=webhook.event_types,
        active=webhook.active,
        created_at=webhook.created_at,
    )


@router.get("/webhooks", response_model=List[RegisterWebhookResponse])
def list_webhooks(
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """List all webhooks for tenant."""
    webhooks = db.query(Webhook).filter(
        Webhook.tenant_id == tenant_id
    ).all()

    return [
        RegisterWebhookResponse(
            id=wh.id,
            url=wh.url,
            event_types=wh.event_types,
            active=wh.active,
            created_at=wh.created_at,
        )
        for wh in webhooks
    ]


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """Delete/unregister webhook."""
    webhook = db.query(Webhook).filter(
        Webhook.id == webhook_id,
        Webhook.tenant_id == tenant_id,
    ).first()

    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )

    db.delete(webhook)
    db.commit()


@router.post("/webhooks/test", response_model=TestWebhookResponse)
def test_webhook(
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Generate test webhook event with signature.

    Returns the event payload and signature for validation.
    """
    test_event = WebhookService.create_test_event(tenant_id)

    return TestWebhookResponse(**test_event)

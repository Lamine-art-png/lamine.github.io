"""Webhook delivery service."""
import logging
import json
import uuid
from datetime import datetime
from typing import Dict, List
from sqlalchemy.orm import Session
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models.webhook import Webhook
from app.core.security import generate_webhook_signature
from app.core.config import settings
from app.core import metrics

logger = logging.getLogger(__name__)


class WebhookService:
    """Handle webhook delivery."""

    @staticmethod
    def get_active_webhooks(
        db: Session, tenant_id: str, event_type: str
    ) -> List[Webhook]:
        """Get active webhooks subscribed to event type."""
        webhooks = (
            db.query(Webhook)
            .filter(
                Webhook.tenant_id == tenant_id,
                Webhook.active == True,
            )
            .all()
        )

        # Filter by event type
        return [
            wh for wh in webhooks
            if event_type in wh.event_types or "*" in wh.event_types
        ]

    @staticmethod
    async def emit_event(
        db: Session,
        tenant_id: str,
        event_type: str,
        data: Dict,
    ):
        """Emit webhook event to all subscribers."""
        if not settings.ENABLE_WEBHOOKS:
            return

        webhooks = WebhookService.get_active_webhooks(db, tenant_id, event_type)

        if not webhooks:
            logger.debug(f"No webhooks for {event_type}")
            return

        event_id = str(uuid.uuid4())
        payload = {
            "id": event_id,
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
            "tenant_id": tenant_id,
        }

        for webhook in webhooks:
            try:
                await WebhookService._deliver_webhook(webhook, payload)
                metrics.webhook_sent.labels(
                    tenant=tenant_id,
                    event_type=event_type,
                    status="success"
                ).inc()
            except Exception as e:
                logger.error(f"Webhook delivery failed: {e}")
                metrics.webhook_sent.labels(
                    tenant=tenant_id,
                    event_type=event_type,
                    status="failure"
                ).inc()

                # Increment failure counter
                failed = int(webhook.failed_deliveries or "0")
                webhook.failed_deliveries = str(failed + 1)

                # Disable after 10 failures
                if failed >= 10:
                    webhook.active = False
                    logger.warning(f"Disabled webhook {webhook.id} after {failed} failures")

        db.commit()

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def _deliver_webhook(webhook: Webhook, payload: Dict):
        """Deliver webhook with retries."""
        payload_str = json.dumps(payload)
        signature = generate_webhook_signature(payload_str)

        headers = {
            "Content-Type": "application/json",
            "X-AgroAI-Signature": signature,
            "X-AgroAI-Event-Type": payload["type"],
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook.url,
                content=payload_str,
                headers=headers,
            )
            response.raise_for_status()

        logger.info(f"Webhook delivered to {webhook.url}")

    @staticmethod
    def create_test_event(tenant_id: str) -> Dict:
        """Create a test webhook event."""
        event_id = str(uuid.uuid4())
        payload = {
            "id": event_id,
            "type": "test.event",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "message": "This is a test webhook event",
                "test": True,
            },
            "tenant_id": tenant_id,
        }

        payload_str = json.dumps(payload)
        signature = generate_webhook_signature(payload_str)

        return {
            "event_id": event_id,
            "event_type": "test.event",
            "payload": payload,
            "signature": signature,
            "timestamp": datetime.utcnow(),
        }

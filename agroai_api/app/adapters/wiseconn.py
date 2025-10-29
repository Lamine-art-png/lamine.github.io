"""WiseConn controller adapter (mock implementation)."""
import uuid
from datetime import datetime
from typing import Dict, Optional
import logging

from app.adapters.base import ControllerAdapter

logger = logging.getLogger(__name__)


class WiseConnAdapter(ControllerAdapter):
    """Mock WiseConn irrigation controller adapter."""

    def __init__(self, api_url: str):
        self.api_url = api_url
        logger.info(f"WiseConn adapter initialized (mock) with URL: {api_url}")

    async def apply_schedule(
        self,
        controller_id: str,
        start_time: datetime,
        duration_min: float,
        zone_ids: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> Dict:
        """Apply schedule to WiseConn controller (mock)."""
        # Mock implementation - in production, make HTTP request to WiseConn API
        provider_schedule_id = f"wc-{uuid.uuid4().hex[:8]}"

        logger.info(
            f"[MOCK] Applied schedule to WiseConn {controller_id}: "
            f"{duration_min}min at {start_time}"
        )

        return {
            "provider_schedule_id": provider_schedule_id,
            "status": "accepted",
        }

    async def cancel_schedule(self, controller_id: str, provider_schedule_id: str) -> bool:
        """Cancel schedule (mock)."""
        logger.info(f"[MOCK] Cancelled WiseConn schedule {provider_schedule_id}")
        return True

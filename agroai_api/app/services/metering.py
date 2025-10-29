"""Usage metering service."""
import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.usage_metering import UsageMetering
from app.core.config import settings


class MeteringService:
    """Track billable usage."""

    @staticmethod
    def record_usage(
        db: Session,
        tenant_id: str,
        endpoint: str,
        unit: str = "request",
        quantity: float = 1.0,
        block_id: str = None,
        metadata: str = None,
    ):
        """Record a usage event."""
        if not settings.ENABLE_METERING:
            return

        usage = UsageMetering(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            endpoint=endpoint,
            unit=unit,
            quantity=quantity,
            block_id=block_id,
            metadata=metadata,
        )

        db.add(usage)
        db.commit()

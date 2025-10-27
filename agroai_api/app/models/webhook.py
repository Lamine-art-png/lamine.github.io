"""Webhook subscription model."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Index, JSON
from datetime import datetime
from app.db.base import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Webhook details
    url = Column(String, nullable=False)
    event_types = Column(JSON, nullable=False)  # List of subscribed event types
    secret = Column(String, nullable=True)  # Optional custom secret

    # Status
    active = Column(Boolean, default=True)
    failed_deliveries = Column(String, default="0")  # Count as string to avoid type issues

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_delivery_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_webhook_active', 'tenant_id', 'active'),
    )

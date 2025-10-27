"""Event model for irrigation/system events."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=True, index=True)

    # Event type
    type = Column(String, nullable=False, index=True)  # irrigation_start, irrigation_stop, alarm, etc.

    # Timestamp
    timestamp = Column(DateTime, nullable=False, index=True)

    # Event data
    event_data = Column(JSON, nullable=True)

    # Source
    source = Column(String, nullable=True)

    # Ingestion tracking
    ingested_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    block = relationship("Block", back_populates="events")

    __table_args__ = (
        Index('ix_events_lookup', 'block_id', 'type', 'timestamp'),
    )

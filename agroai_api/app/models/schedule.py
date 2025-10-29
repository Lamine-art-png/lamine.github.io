"""Schedule model for irrigation schedules."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, JSON, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=True, index=True)
    controller_id = Column(String, nullable=True, index=True)

    # Schedule details
    start_time = Column(DateTime, nullable=False)
    duration_min = Column(Float, nullable=False)
    volume_m3 = Column(Float, nullable=True)

    # Status: pending, active, completed, cancelled
    status = Column(String, default="pending", index=True)

    # Provider info
    provider = Column(String, nullable=True)  # wiseconn, rainbird, etc.
    provider_schedule_id = Column(String, nullable=True)

    # Metadata
    meta_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_schedule_status', 'status', 'start_time'),
    )

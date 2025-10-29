"""Telemetry model for sensor data."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)

    # Type: soil_vwc | et0 | weather | flow | valve_state
    type = Column(String, nullable=False, index=True)

    # Timestamp of measurement
    timestamp = Column(DateTime, nullable=False, index=True)

    # Value and unit
    value = Column(Float, nullable=False)
    unit = Column(String, nullable=True)

    # Metadata
    source = Column(String, nullable=True)  # sensor ID, API, manual
    meta_data = Column(JSON, nullable=True)

    # Ingestion tracking
    ingested_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    block = relationship("Block", back_populates="telemetry")

    __table_args__ = (
        Index('ix_telemetry_lookup', 'block_id', 'type', 'timestamp'),
    )

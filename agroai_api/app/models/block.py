"""Block (field/zone) model."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Block(Base):
    __tablename__ = "blocks"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    area_ha = Column(Float, nullable=False)
    crop_type = Column(String, nullable=True)
    soil_type = Column(String, nullable=True)

    # Location
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Configuration
    config = Column(JSON, nullable=True)  # flexible config storage

    # Water budget (m3)
    water_budget_allocated = Column(Float, nullable=True)
    water_budget_used = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="blocks")
    telemetry = relationship("Telemetry", back_populates="block")
    events = relationship("Event", back_populates="block")
    recommendations = relationship("Recommendation", back_populates="block")

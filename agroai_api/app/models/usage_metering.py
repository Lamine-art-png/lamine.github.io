"""Usage metering model for billing."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index
from datetime import datetime
from app.db.base import Base


class UsageMetering(Base):
    __tablename__ = "usage_metering"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Metering details
    endpoint = Column(String, nullable=False)  # e.g., "/v1/blocks/{id}/recommendations:compute"
    unit = Column(String, default="request")  # request, compute_hour, etc.
    quantity = Column(Float, default=1.0)

    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Metadata (for detailed tracking)
    block_id = Column(String, nullable=True)
    meta_data = Column(String, nullable=True)

    __table_args__ = (
        Index('ix_usage_tenant_time', 'tenant_id', 'timestamp'),
        Index('ix_usage_endpoint', 'endpoint', 'timestamp'),
    )

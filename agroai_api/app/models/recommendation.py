"""Recommendation model with idempotency support."""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)

    # Idempotency key (unique per tenant for 24h)
    idempotency_key = Column(String, nullable=True, index=True)

    # Request hash for body-based deduplication
    body_hash = Column(String, nullable=True, index=True)

    # Feature hash for cache lookup
    feature_hash = Column(String, nullable=True, index=True)

    # Recommendation details
    when = Column(DateTime, nullable=False)  # When to irrigate
    duration_min = Column(Float, nullable=False)
    volume_m3 = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)  # 0-1

    # Horizon
    horizon_hours = Column(Float, nullable=False)

    # Explanations and metadata
    explanations = Column(JSON, nullable=True)  # List of explanation strings
    version = Column(String, nullable=False)  # Model version e.g. "rf-ens-1.0.0"
    meta_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)  # For cache TTL

    # Relationships
    block = relationship("Block", back_populates="recommendations")

    __table_args__ = (
        Index('ix_rec_idem', 'tenant_id', 'idempotency_key', 'body_hash'),
        Index('ix_rec_cache', 'block_id', 'feature_hash', 'expires_at'),
        Index('ix_rec_block_date', 'block_id', 'created_at'),
    )

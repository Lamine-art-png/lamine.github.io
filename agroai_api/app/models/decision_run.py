"""Decision run — tracks the full lifecycle of one irrigation decision.

Links recommendation → schedule → execution verification.
Lifecycle: recommended → approved → scheduled → applied → verified
"""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON
from datetime import datetime
from app.db.base import Base


class DecisionRun(Base):
    __tablename__ = "decision_runs"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)

    # Lifecycle status: recommended | approved | scheduled | applied | verified | failed
    status = Column(String, nullable=False, default="recommended", index=True)

    # Links
    recommendation_id = Column(String, ForeignKey("recommendations.id"), nullable=False, index=True)
    schedule_id = Column(String, ForeignKey("schedules.id"), nullable=True, index=True)
    verification_id = Column(String, nullable=True, index=True)  # FK added after verification model exists

    # Planned values (from recommendation)
    planned_start = Column(DateTime, nullable=False)
    planned_duration_min = Column(Float, nullable=False)
    planned_volume_m3 = Column(Float, nullable=False)

    # Actual values (from provider schedule/event)
    actual_start = Column(DateTime, nullable=True)
    actual_duration_min = Column(Float, nullable=True)
    actual_volume_m3 = Column(Float, nullable=True)

    # Provider info
    provider = Column(String, nullable=True)  # wiseconn, rainbird, etc.
    provider_event_id = Column(String, nullable=True)

    # Engine version that produced the recommendation
    engine_version = Column(String, nullable=True)

    # Timestamps
    recommended_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('ix_dr_block_status', 'block_id', 'status'),
        Index('ix_dr_tenant_block', 'tenant_id', 'block_id'),
        Index('ix_dr_schedule', 'schedule_id'),
    )

"""Persistent forecast model — one snapshot per block per forecast cycle.

Stores VWC forecast trajectories for accuracy tracking and auditability.
"""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON
from datetime import datetime
from app.db.base import Base


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)

    # When this forecast was computed
    computed_at = Column(DateTime, nullable=False, index=True)

    # Current VWC at time of forecast
    current_vwc = Column(Float, nullable=False)

    # Forecast points: JSON array of {hours_ahead, predicted_vwc, stress_risk, below_stress, confidence}
    points = Column(JSON, nullable=False)

    # Hours until stress threshold (null if not on track to stress)
    hours_to_stress = Column(Float, nullable=True)

    # Optimal irrigation window: "now" | "within_Xh" | "not_needed"
    optimal_irrigation_window = Column(String, nullable=True)

    # Overall forecast confidence (0-1)
    confidence = Column(Float, nullable=False)

    # Crop/soil profile used (e.g. "corn/loam")
    profile_used = Column(String, nullable=False)

    # Forecast engine version
    forecast_version = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_fc_block_time', 'block_id', 'computed_at'),
        Index('ix_fc_tenant_block', 'tenant_id', 'block_id'),
    )

"""Persistent water state model — one snapshot per block per estimation cycle.

Captures the inferred root-zone condition so downstream services
(recommender, forecast, execution verifier) share a single source of truth.
"""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON, Boolean
from datetime import datetime
from app.db.base import Base


class WaterState(Base):
    __tablename__ = "water_states"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)

    # When this estimate was computed
    estimated_at = Column(DateTime, nullable=False, index=True)

    # Root-zone weighted VWC (0-1 scale, weighted across depths)
    root_zone_vwc = Column(Float, nullable=False)

    # Per-depth readings used (JSON array of {depth_inches, vwc, timestamp})
    depth_profile = Column(JSON, nullable=True)

    # Stress risk (0 = no stress, 1 = critical stress)
    stress_risk = Column(Float, nullable=False)

    # Refill status: depleting | stable | refilling | saturated | unknown
    refill_status = Column(String, nullable=False)

    # How quickly VWC is changing (percent per hour, negative = drying)
    depletion_rate = Column(Float, nullable=True)

    # Hours until stress threshold at current depletion rate (null = not depleting)
    hours_to_stress = Column(Float, nullable=True)

    # ET demand (mm/day, recent average)
    et_demand_mm_day = Column(Float, nullable=True)

    # Last irrigation: when and how much
    last_irrigation_at = Column(DateTime, nullable=True)
    last_irrigation_volume_m3 = Column(Float, nullable=True)

    # Confidence (0-1) — based on data freshness, coverage, consistency
    confidence = Column(Float, nullable=False)

    # Anomaly flags (JSON list of anomaly codes)
    # e.g. ["stale_data", "sensor_drift", "unexpected_refill", "missing_depth"]
    anomaly_flags = Column(JSON, nullable=True)

    # Feature snapshot used (for reproducibility and auditability)
    feature_snapshot = Column(JSON, nullable=True)

    # Model version that produced this estimate
    engine_version = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_ws_block_time', 'block_id', 'estimated_at'),
        Index('ix_ws_tenant_block', 'tenant_id', 'block_id'),
        Index('ix_ws_stress', 'block_id', 'stress_risk'),
    )

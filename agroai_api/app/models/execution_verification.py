"""Execution verification — measures what actually happened vs what was planned.

One verification per decision run. Captures:
- Planned vs actual duration/volume deviations
- Post-irrigation soil response at 24h and 48h
- Outcome classification
- Deviation reasons
"""
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index, JSON
from datetime import datetime
from app.db.base import Base


class ExecutionVerification(Base):
    __tablename__ = "execution_verifications"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    block_id = Column(String, ForeignKey("blocks.id"), nullable=False, index=True)
    decision_run_id = Column(String, ForeignKey("decision_runs.id"), nullable=False, index=True)

    # Execution comparison
    planned_duration_min = Column(Float, nullable=False)
    actual_duration_min = Column(Float, nullable=True)
    duration_deviation_pct = Column(Float, nullable=True)  # (actual - planned) / planned * 100

    planned_volume_m3 = Column(Float, nullable=False)
    actual_volume_m3 = Column(Float, nullable=True)
    volume_deviation_pct = Column(Float, nullable=True)

    planned_start = Column(DateTime, nullable=False)
    actual_start = Column(DateTime, nullable=True)
    start_delay_minutes = Column(Float, nullable=True)  # actual - planned in minutes

    # Pre-irrigation soil state
    pre_irrigation_vwc = Column(Float, nullable=True)
    pre_irrigation_stress_risk = Column(Float, nullable=True)

    # Post-irrigation soil response
    post_24h_vwc = Column(Float, nullable=True)       # VWC 24 hours after irrigation
    post_48h_vwc = Column(Float, nullable=True)       # VWC 48 hours after irrigation
    vwc_delta_24h = Column(Float, nullable=True)       # post_24h - pre
    vwc_delta_48h = Column(Float, nullable=True)       # post_48h - pre
    peak_vwc_after = Column(Float, nullable=True)      # Maximum VWC observed post-irrigation
    hours_to_peak = Column(Float, nullable=True)       # Hours from irrigation start to peak VWC

    # Outcome classification:
    #   matched           — applied within tolerance, soil responded as expected
    #   partially_matched — applied but with significant deviations
    #   deviated          — duration/volume differ substantially from plan
    #   failed            — irrigation did not execute or was cancelled
    #   agronomically_ineffective — applied but no measurable soil response
    outcome = Column(String, nullable=False, index=True)

    # Deviation reasons (JSON list of reason codes)
    # e.g. ["duration_short", "volume_excess", "no_soil_response", "delayed_start"]
    deviation_reasons = Column(JSON, nullable=True)

    # Verification status: pending_24h | pending_48h | complete | insufficient_data
    verification_status = Column(String, nullable=False, default="pending_24h", index=True)

    # Confidence in this verification (0-1)
    confidence = Column(Float, nullable=True)

    # Agronomic effectiveness score (0-1): did the soil actually benefit?
    effectiveness_score = Column(Float, nullable=True)

    # Raw data snapshots for auditability
    pre_snapshot = Column(JSON, nullable=True)   # water state before irrigation
    post_snapshot = Column(JSON, nullable=True)  # water state after irrigation

    # Engine version
    verifier_version = Column(String, nullable=False)

    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('ix_ev_block_outcome', 'block_id', 'outcome'),
        Index('ix_ev_tenant_block', 'tenant_id', 'block_id'),
        Index('ix_ev_status', 'verification_status'),
        Index('ix_ev_decision_run', 'decision_run_id'),
    )

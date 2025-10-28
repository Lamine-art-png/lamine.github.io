"""Ingestion run audit model for tracking all data ingestion attempts."""
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Index, Boolean, Text
from datetime import datetime
from app.db.base import Base


class IngestionRun(Base):
    """Track every data ingestion attempt for audit and debugging."""

    __tablename__ = "ingestion_runs"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    field_id = Column(String, ForeignKey("blocks.id"), nullable=True, index=True)

    # Source information
    source_type = Column(String, nullable=False)  # file | s3 | azure
    source_uri = Column(String, nullable=False)  # Full path/URL
    source_checksum = Column(String, nullable=True)  # SHA-256 of source data

    # Processing details
    status = Column(String, nullable=False, index=True)  # pending | processing | success | failed
    data_type = Column(String, nullable=False)  # telemetry | weather | soil | flow

    # Counts and metrics
    rows_total = Column(Integer, default=0)
    rows_accepted = Column(Integer, default=0)
    rows_rejected = Column(Integer, default=0)

    # Timing
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)  # JSON serialized error context

    # Orchestration context
    batch_id = Column(String, nullable=True, index=True)  # Group related ingestion runs
    triggered_by = Column(String, nullable=True)  # manual | scheduled | webhook

    __table_args__ = (
        Index('ix_ingestion_status_time', 'status', 'started_at'),
        Index('ix_ingestion_tenant_time', 'tenant_id', 'started_at'),
        Index('ix_ingestion_batch', 'batch_id', 'started_at'),
    )

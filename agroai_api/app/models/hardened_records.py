"""ORM projections for hardening columns added after the original operational models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, JSON, String

from app.db.base import Base


class DataSourceIdentity(Base):
    __tablename__ = "data_sources"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    connector_connection_id = Column(String, nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    object_size_bytes = Column(BigInteger, nullable=True)


class IngestionJobState(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    input_json = Column(JSON, nullable=False)
    output_json = Column(JSON, nullable=False)
    error = Column(String, nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    worker_id = Column(String, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class EvidenceFreshnessState(Base):
    __tablename__ = "evidence_records"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    source_updated_at = Column(DateTime, nullable=True)


class IntelligenceRunProvenanceState(Base):
    __tablename__ = "intelligence_runs"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    provenance_json = Column(JSON, nullable=True)
    freshness_json = Column(JSON, nullable=True)

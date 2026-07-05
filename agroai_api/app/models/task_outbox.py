from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_task_outbox_job"),
        Index("ix_task_outbox_pending", "status", "next_attempt_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task_type = Column(String, nullable=False)
    payload_json = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="pending")
    publish_attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

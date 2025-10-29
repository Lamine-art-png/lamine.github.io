"""Audit log model."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, JSON
from datetime import datetime
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Action details
    action = Column(String, nullable=False, index=True)  # compute, apply, cancel, etc.
    resource_type = Column(String, nullable=False)  # recommendation, schedule, controller
    resource_id = Column(String, nullable=True, index=True)

    # User/client info
    actor = Column(String, nullable=True)  # Client ID or user ID

    # Result
    status = Column(String, nullable=False)  # success, failure
    details = Column(JSON, nullable=True)

    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('ix_audit_tenant_time', 'tenant_id', 'timestamp'),
        Index('ix_audit_action', 'action', 'timestamp'),
    )

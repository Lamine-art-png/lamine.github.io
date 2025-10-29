"""Audit logging service."""
import uuid
from datetime import datetime
from typing import Optional, Dict
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditService:
    """Audit log service."""

    @staticmethod
    def log(
        db: Session,
        tenant_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        actor: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict] = None,
    ):
        """Log an audit event."""
        log_entry = AuditLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            status=status,
            details=details,
        )

        db.add(log_entry)
        db.commit()

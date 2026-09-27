"""Customer-facing Portal legal acceptance records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


def new_legal_id() -> str:
    return str(uuid.uuid4())


class CustomerLegalAcceptance(Base):
    __tablename__ = "customer_legal_acceptances"
    __table_args__ = (
        Index("ix_customer_legal_acceptance_org_time", "organization_id", "accepted_at"),
        Index("ix_customer_legal_acceptance_user_time", "user_id", "accepted_at"),
        Index("ix_customer_legal_acceptance_versions", "terms_version", "privacy_version", "accepted_at"),
    )

    id = Column(String, primary_key=True, default=new_legal_id)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_email = Column(String, nullable=False)
    event_type = Column(String, nullable=False, index=True)
    terms_version = Column(String, nullable=False)
    privacy_version = Column(String, nullable=False)
    terms_effective_date = Column(String, nullable=False)
    privacy_effective_date = Column(String, nullable=False)
    terms_url = Column(String, nullable=False)
    privacy_url = Column(String, nullable=False)
    terms_reference_digest = Column(String(64), nullable=False)
    privacy_reference_digest = Column(String(64), nullable=False)
    acceptance_text = Column(Text, nullable=False)
    accepted_terms = Column(Boolean, nullable=False)
    acknowledged_privacy = Column(Boolean, nullable=False)
    authority_confirmed = Column(Boolean, nullable=False)
    order_snapshot_json = Column(JSON, nullable=True)
    ip_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    request_id = Column(String, nullable=True, index=True)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    organization = relationship("Organization")
    user = relationship("User")

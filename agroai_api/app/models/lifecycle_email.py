"""Lifecycle onboarding email state (see alembic 038_lifecycle_emails)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db.base import Base


def _id() -> str:
    return str(uuid.uuid4())


class LifecycleEmailEnrollment(Base):
    __tablename__ = "lifecycle_email_enrollments"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    sequence_version = Column(String(40), nullable=False)
    source = Column(String(40), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    stop_reason = Column(String(80), nullable=True)
    enrolled_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    stopped_at = Column(DateTime, nullable=True)
    unsubscribed_at = Column(DateTime, nullable=True)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class LifecycleEmailSend(Base):
    __tablename__ = "lifecycle_email_sends"
    __table_args__ = (UniqueConstraint("user_id", "step", name="uq_lifecycle_email_sends_user_step"),)

    id = Column(String, primary_key=True, default=_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    step = Column(String(40), nullable=False)
    status = Column(String(32), nullable=False)
    reason = Column(String(120), nullable=True)
    variant = Column(String(40), nullable=True)
    scheduled_for = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    locale = Column(String(40), nullable=True)
    plan_at_send = Column(String(40), nullable=True)
    provider = Column(String(40), nullable=True)
    provider_message_id = Column(String(200), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)
    bounced_at = Column(DateTime, nullable=True)
    activation_event = Column(String(60), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

"""Invitation token model for secure tenant onboarding."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Index
from datetime import datetime
from app.db.base import Base


class InvitationToken(Base):
    """Secure tokens for inviting new users to tenants."""

    __tablename__ = "invitation_tokens"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Token details
    token_hash = Column(String, nullable=False, unique=True, index=True)  # SHA-256
    role = Column(String, default="analyst", nullable=False)  # Role for new user

    # Usage constraints
    max_uses = Column(String, default="1")  # How many times token can be used
    uses_count = Column(String, default="0")  # Current use count

    # Validity
    active = Column(Boolean, default=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)

    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=True)  # Who created the invitation

    # Redemption tracking
    redeemed_at = Column(DateTime, nullable=True)
    redeemed_by = Column(String, nullable=True)  # Email or identifier of redeemer

    __table_args__ = (
        Index('ix_invitation_tenant_active', 'tenant_id', 'active'),
    )

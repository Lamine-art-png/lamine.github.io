"""API Key model for tenant authentication and authorization."""
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Index, JSON
from datetime import datetime
from app.db.base import Base


class APIKey(Base):
    """Tenant-scoped API keys with optional field restrictions."""

    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    # Key details
    key_hash = Column(String, nullable=False, unique=True, index=True)  # SHA-256 of actual key
    key_prefix = Column(String, nullable=False)  # First 8 chars for identification
    name = Column(String, nullable=False)  # Human-readable name

    # Permissions
    role = Column(String, default="analyst", nullable=False)  # owner | analyst | viewer
    field_restrictions = Column(JSON, nullable=True)  # Optional list of allowed field IDs

    # Status
    active = Column(Boolean, default=True, index=True)

    # Usage tracking
    last_used_at = Column(DateTime, nullable=True)
    usage_count = Column(String, default="0")  # String to avoid int overflow

    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by = Column(String, nullable=True)  # User/system that created key
    expires_at = Column(DateTime, nullable=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String, nullable=True)
    revoke_reason = Column(String, nullable=True)

    __table_args__ = (
        Index('ix_apikey_tenant_active', 'tenant_id', 'active'),
        Index('ix_apikey_expires', 'expires_at', 'active'),
    )

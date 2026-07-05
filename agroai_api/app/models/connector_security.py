from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint

from app.db.base import Base


def new_security_id() -> str:
    return str(uuid.uuid4())


class OAuthStateNonce(Base):
    __tablename__ = "oauth_state_nonces"
    __table_args__ = (
        UniqueConstraint("nonce_hash", name="uq_oauth_state_nonce_hash"),
        Index("ix_oauth_state_pending_lookup", "connection_id", "provider", "consumed_at", "expires_at"),
    )

    id = Column(String, primary_key=True, default=new_security_id)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String, nullable=False)
    purpose = Column(String, nullable=False)
    nonce_hash = Column(String(64), nullable=False, unique=True)
    redirect_sha256 = Column(String(64), nullable=False)
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ConnectorCredential(Base):
    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint("connection_id", name="uq_connector_credential_connection"),
        Index("ix_connector_credentials_active", "tenant_id", "provider", "revoked_at"),
    )

    id = Column(String, primary_key=True, default=new_security_id)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, unique=True)
    provider = Column(String, nullable=False, index=True)
    key_version = Column(String, nullable=False)
    algorithm = Column(String, nullable=False, default="AES-256-GCM")
    nonce_b64 = Column(Text, nullable=False)
    ciphertext_b64 = Column(Text, nullable=False)
    token_expires_at = Column(DateTime, nullable=True)
    scopes_json = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

"""WhatsApp field-channel persistence.

The official WhatsApp Cloud API is treated as an authenticated edge channel into
Field Intelligence. Phone identifiers are never stored in plaintext. Webhook
events and outbound requests are idempotent and independently retryable.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class WhatsAppContactBinding(Base):
    __tablename__ = "whatsapp_contact_bindings"

    id = Column(String, primary_key=True, default=new_id)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    connector_connection_id = Column(
        String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    wa_id_hash = Column(String(64), nullable=False)
    wa_id_ciphertext_b64 = Column(Text, nullable=False)
    wa_id_nonce_b64 = Column(String(64), nullable=False)
    wa_id_key_version = Column(String(40), nullable=False, default="derived-v1")
    masked_wa_id = Column(String(40), nullable=False)

    role = Column(String(40), nullable=False, default="operator")
    locale = Column(String(20), nullable=False, default="en")
    status = Column(String(32), nullable=False, default="pending", index=True)
    consent_status = Column(String(32), nullable=False, default="unknown", index=True)
    consent_granted_at = Column(DateTime, nullable=True)
    consent_revoked_at = Column(DateTime, nullable=True)
    context_json = Column(JSON, nullable=False, default=dict)

    last_inbound_at = Column(DateTime, nullable=True)
    last_outbound_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connector_connection_id", "wa_id_hash",
            name="uq_whatsapp_binding_identity",
        ),
        Index("ix_whatsapp_binding_tenant_status", "tenant_id", "status", "updated_at"),
    )


class WhatsAppInboundEvent(Base):
    __tablename__ = "whatsapp_inbound_events"

    id = Column(String, primary_key=True, default=new_id)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    connector_connection_id = Column(
        String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_binding_id = Column(
        String, ForeignKey("whatsapp_contact_bindings.id", ondelete="SET NULL"), nullable=True, index=True
    )

    meta_message_id = Column(String(240), nullable=True, index=True)
    payload_hash = Column(String(64), nullable=False)
    event_type = Column(String(32), nullable=False, default="message", index=True)
    message_type = Column(String(32), nullable=True, index=True)
    delivery_status = Column(String(32), nullable=True)

    text_content = Column(Text, nullable=True)
    media_id = Column(String(240), nullable=True)
    media_mime_type = Column(String(200), nullable=True)
    media_filename = Column(String(240), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    occurred_at = Column(DateTime, nullable=True)

    status = Column(String(32), nullable=False, default="queued", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    worker_id = Column(String(120), nullable=True)
    last_error = Column(Text, nullable=True)

    capture_session_id = Column(String, nullable=True, index=True)
    observation_id = Column(String, nullable=True, index=True)
    redacted_payload_json = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "connector_connection_id", "payload_hash",
            name="uq_whatsapp_inbound_payload",
        ),
        Index("ix_whatsapp_inbound_claim", "status", "next_attempt_at", "lease_expires_at"),
        Index("ix_whatsapp_inbound_tenant_time", "tenant_id", "created_at"),
    )


class WhatsAppOutboundMessage(Base):
    __tablename__ = "whatsapp_outbound_messages"

    id = Column(String, primary_key=True, default=new_id)
    tenant_id = Column(String, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True, index=True)
    connector_connection_id = Column(
        String, ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_binding_id = Column(
        String, ForeignKey("whatsapp_contact_bindings.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    idempotency_key = Column(String(180), nullable=False)
    message_kind = Column(String(32), nullable=False, default="text")
    template_name = Column(String(200), nullable=True)
    language_code = Column(String(20), nullable=True)
    body_text = Column(Text, nullable=True)
    parameters_json = Column(JSON, nullable=False, default=list)
    meta_message_id = Column(String(240), nullable=True, index=True)

    status = Column(String(32), nullable=False, default="queued", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    worker_id = Column(String(120), nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_whatsapp_outbound_idempotency"),
        Index("ix_whatsapp_outbound_claim", "status", "next_attempt_at", "lease_expires_at"),
        Index("ix_whatsapp_outbound_tenant_time", "tenant_id", "created_at"),
    )

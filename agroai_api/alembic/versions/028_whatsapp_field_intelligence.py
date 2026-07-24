"""WhatsApp Field Intelligence channel.

Revision ID: 028_whatsapp_field_intelligence
Revises: 027_field_intelligence_launch
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "028_whatsapp_field_intelligence"
down_revision = "027_field_intelligence_launch"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def upgrade() -> None:
    if not _has_table("whatsapp_contact_bindings"):
        op.create_table(
            "whatsapp_contact_bindings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("connector_connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("wa_id_hash", sa.String(length=64), nullable=False),
            sa.Column("wa_id_ciphertext_b64", sa.Text(), nullable=False),
            sa.Column("wa_id_nonce_b64", sa.String(length=64), nullable=False),
            sa.Column("wa_id_key_version", sa.String(length=40), nullable=False, server_default="derived-v1"),
            sa.Column("masked_wa_id", sa.String(length=40), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False, server_default="operator"),
            sa.Column("locale", sa.String(length=20), nullable=False, server_default="en"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("consent_status", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("consent_granted_at", sa.DateTime(), nullable=True),
            sa.Column("consent_revoked_at", sa.DateTime(), nullable=True),
            sa.Column("context_json", sa.JSON(), nullable=False),
            sa.Column("last_inbound_at", sa.DateTime(), nullable=True),
            sa.Column("last_outbound_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "connector_connection_id", "wa_id_hash",
                name="uq_whatsapp_binding_identity",
            ),
        )
        op.create_index("ix_whatsapp_binding_tenant_status", "whatsapp_contact_bindings", ["tenant_id", "status", "updated_at"])
        op.create_index("ix_whatsapp_contact_bindings_tenant_id", "whatsapp_contact_bindings", ["tenant_id"])
        op.create_index("ix_whatsapp_contact_bindings_workspace_id", "whatsapp_contact_bindings", ["workspace_id"])
        op.create_index("ix_whatsapp_contact_bindings_connector_connection_id", "whatsapp_contact_bindings", ["connector_connection_id"])
        op.create_index("ix_whatsapp_contact_bindings_user_id", "whatsapp_contact_bindings", ["user_id"])
        op.create_index("ix_whatsapp_contact_bindings_status", "whatsapp_contact_bindings", ["status"])
        op.create_index("ix_whatsapp_contact_bindings_consent_status", "whatsapp_contact_bindings", ["consent_status"])

    if not _has_table("whatsapp_inbound_events"):
        op.create_table(
            "whatsapp_inbound_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("connector_connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("contact_binding_id", sa.String(), sa.ForeignKey("whatsapp_contact_bindings.id", ondelete="SET NULL"), nullable=True),
            sa.Column("meta_message_id", sa.String(length=240), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False, server_default="message"),
            sa.Column("message_type", sa.String(length=32), nullable=True),
            sa.Column("delivery_status", sa.String(length=32), nullable=True),
            sa.Column("text_content", sa.Text(), nullable=True),
            sa.Column("media_id", sa.String(length=240), nullable=True),
            sa.Column("media_mime_type", sa.String(length=200), nullable=True),
            sa.Column("media_filename", sa.String(length=240), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("worker_id", sa.String(length=120), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("capture_session_id", sa.String(), nullable=True),
            sa.Column("observation_id", sa.String(), nullable=True),
            sa.Column("redacted_payload_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("connector_connection_id", "payload_hash", name="uq_whatsapp_inbound_payload"),
        )
        op.create_index("ix_whatsapp_inbound_claim", "whatsapp_inbound_events", ["status", "next_attempt_at", "lease_expires_at"])
        op.create_index("ix_whatsapp_inbound_tenant_time", "whatsapp_inbound_events", ["tenant_id", "created_at"])
        for column in (
            "tenant_id", "workspace_id", "connector_connection_id", "contact_binding_id",
            "meta_message_id", "event_type", "message_type", "status",
            "capture_session_id", "observation_id", "created_at",
        ):
            op.create_index(f"ix_whatsapp_inbound_events_{column}", "whatsapp_inbound_events", [column])

    if not _has_table("whatsapp_outbound_messages"):
        op.create_table(
            "whatsapp_outbound_messages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("connector_connection_id", sa.String(), sa.ForeignKey("connector_connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("contact_binding_id", sa.String(), sa.ForeignKey("whatsapp_contact_bindings.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("idempotency_key", sa.String(length=180), nullable=False),
            sa.Column("message_kind", sa.String(length=32), nullable=False, server_default="text"),
            sa.Column("template_name", sa.String(length=200), nullable=True),
            sa.Column("language_code", sa.String(length=20), nullable=True),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("meta_message_id", sa.String(length=240), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("worker_id", sa.String(length=120), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_whatsapp_outbound_idempotency"),
        )
        op.create_index("ix_whatsapp_outbound_claim", "whatsapp_outbound_messages", ["status", "next_attempt_at", "lease_expires_at"])
        op.create_index("ix_whatsapp_outbound_tenant_time", "whatsapp_outbound_messages", ["tenant_id", "created_at"])
        for column in (
            "tenant_id", "workspace_id", "connector_connection_id", "contact_binding_id",
            "meta_message_id", "status", "created_at",
        ):
            op.create_index(f"ix_whatsapp_outbound_messages_{column}", "whatsapp_outbound_messages", [column])


def downgrade() -> None:
    for table in (
        "whatsapp_outbound_messages",
        "whatsapp_inbound_events",
        "whatsapp_contact_bindings",
    ):
        if _has_table(table):
            op.drop_table(table)

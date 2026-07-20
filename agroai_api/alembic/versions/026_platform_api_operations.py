"""Add Platform API support, status, and abuse operations.

Revision ID: 026_platform_api_operations
Revises: 025_platform_api_commerce
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "026_platform_api_operations"
down_revision = "025_platform_api_commerce"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "platform_support_requests",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_to_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("request_id_reference", sa.String(), nullable=True),
        sa.Column("key_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("webhook_delivery_id", sa.String(), nullable=True),
        sa.Column("invoice_reference", sa.String(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=False),
        sa.Column("attachment_references_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_support_org_status", "platform_support_requests", ["organization_id", "status", "created_at"])
    op.create_index("ix_platform_support_queue", "platform_support_requests", ["severity", "status", "created_at"])

    op.create_table(
        "platform_support_messages",
        _id(),
        sa.Column("support_request_id", sa.String(), sa.ForeignKey("platform_support_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_support_message_request", "platform_support_messages", ["support_request_id", "created_at"])

    op.create_table(
        "platform_status_components",
        _id(),
        sa.Column("component_key", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "platform_status_incidents",
        _id(),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("public_summary", sa.Text(), nullable=False),
        sa.Column("component_keys_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_status_incident_state", "platform_status_incidents", ["status", "started_at"])

    op.create_table(
        "platform_status_incident_updates",
        _id(),
        sa.Column("incident_id", sa.String(), sa.ForeignKey("platform_status_incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("public_message", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_status_update_incident", "platform_status_incident_updates", ["incident_id", "created_at"])

    op.create_table(
        "platform_abuse_events",
        _id(),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("api_key_id", sa.String(), sa.ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("automated_action", sa.String(), nullable=True),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_platform_abuse_org_state", "platform_abuse_events", ["organization_id", "status", "created_at"])
    op.create_index("ix_platform_abuse_signal", "platform_abuse_events", ["signal_type", "created_at"])


def downgrade() -> None:
    for table in (
        "platform_abuse_events",
        "platform_status_incident_updates",
        "platform_status_incidents",
        "platform_status_components",
        "platform_support_messages",
        "platform_support_requests",
    ):
        op.drop_table(table)

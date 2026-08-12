"""Add the agroai CLI device-authorization table (RFC 8628-style human login).

Revision ID: 029_platform_cli_device_auth
Revises: 028_platform_api_live_catalog
Create Date: 2026-08-12

Durable storage for browser-assisted device authorization so the `agroai` CLI
can obtain a short-lived, organization-scoped human control-plane token without
embedding a client secret and without using an API key as human identity. The
device_code is stored only as a hash; the human-readable user_code is unique.
The feature is gated by PLATFORM_API_CLI_DEVICE_AUTH_ENABLED (default off).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "029_platform_cli_device_auth"
down_revision = "028_platform_api_live_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_cli_device_authorizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("device_code_hash", sa.String(), nullable=False),
        sa.Column("user_code", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("approved_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_scope", sa.String(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_label", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("device_code_hash", name="uq_cli_device_code_hash"),
        sa.UniqueConstraint("user_code", name="uq_cli_device_user_code"),
    )
    op.create_index("ix_cli_device_status", "platform_cli_device_authorizations", ["status"])
    op.create_index("ix_cli_device_expires_at", "platform_cli_device_authorizations", ["expires_at"])
    op.create_index("ix_cli_device_organization_id", "platform_cli_device_authorizations", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_cli_device_organization_id", table_name="platform_cli_device_authorizations")
    op.drop_index("ix_cli_device_expires_at", table_name="platform_cli_device_authorizations")
    op.drop_index("ix_cli_device_status", table_name="platform_cli_device_authorizations")
    op.drop_table("platform_cli_device_authorizations")

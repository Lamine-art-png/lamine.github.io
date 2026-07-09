"""Add durable AGRO-AI founder outreach suppression and send ledger.

Revision ID: 017_outreach_machine
Revises: 016_commercial_control_plane
Create Date: 2026-07-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017_outreach_machine"
down_revision = "016_commercial_control_plane"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_table("outreach_suppression"):
        op.create_table(
            "outreach_suppression",
            sa.Column("email", sa.String(length=320), primary_key=True),
            sa.Column("reason", sa.String(length=240), nullable=False),
            sa.Column("created_at", sa.String(length=64), nullable=False),
        )

    if not _has_table("outreach_sends"):
        op.create_table(
            "outreach_sends",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("prospect_id", sa.String(length=128), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("account", sa.String(length=250), nullable=False),
            sa.Column("subject", sa.String(length=250), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("resend_id", sa.String(length=128), nullable=True),
            sa.Column("idempotency_key", sa.String(length=256), nullable=False),
            sa.Column("dry_run", sa.Integer(), nullable=False),
            sa.Column("error_text", sa.String(length=2000), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=64), nullable=False),
        )

    if "ix_outreach_sends_email_created" not in _indexes("outreach_sends"):
        op.create_index(
            "ix_outreach_sends_email_created",
            "outreach_sends",
            ["email", "created_at"],
        )
    if "ix_outreach_sends_status_created" not in _indexes("outreach_sends"):
        op.create_index(
            "ix_outreach_sends_status_created",
            "outreach_sends",
            ["status", "created_at"],
        )
    if "ix_outreach_sends_idempotency_key" not in _indexes("outreach_sends"):
        op.create_index(
            "ix_outreach_sends_idempotency_key",
            "outreach_sends",
            ["idempotency_key"],
        )


def downgrade() -> None:
    if _has_table("outreach_sends"):
        op.drop_table("outreach_sends")
    if _has_table("outreach_suppression"):
        op.drop_table("outreach_suppression")

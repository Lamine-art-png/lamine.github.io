"""Add durable first-party outreach engagement events.

Revision ID: 018_outreach_engagement
Revises: 017_outreach_machine
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "018_outreach_engagement"
down_revision = "017_outreach_machine"
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
    if not _has_table("outreach_events"):
        op.create_table(
            "outreach_events",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("send_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=96), nullable=False),
            sa.Column("link_key", sa.String(length=32), nullable=True),
            sa.Column("user_agent", sa.String(length=500), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ["send_id"],
                ["outreach_sends.id"],
                name="fk_outreach_events_send_id",
                ondelete="CASCADE",
            ),
        )

    if "ix_outreach_events_send_created" not in _indexes("outreach_events"):
        op.create_index(
            "ix_outreach_events_send_created",
            "outreach_events",
            ["send_id", "created_at"],
        )
    if "ix_outreach_events_type_created" not in _indexes("outreach_events"):
        op.create_index(
            "ix_outreach_events_type_created",
            "outreach_events",
            ["event_type", "created_at"],
        )


def downgrade() -> None:
    if _has_table("outreach_events"):
        op.drop_table("outreach_events")

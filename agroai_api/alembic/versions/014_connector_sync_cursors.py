"""Add durable provider synchronization cursors.

Revision ID: 014_connector_sync_cursors
Revises: 013_task_outbox
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "014_connector_sync_cursors"
down_revision = "013_task_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "connector_sync_cursors" not in inspector.get_table_names():
        op.create_table(
            "connector_sync_cursors",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("connection_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("cursor", sa.Text(), nullable=True),
            sa.Column("cursor_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["connection_id"], ["connector_connections.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "connection_id", name="uq_connector_sync_cursor_connection"),
        )

    inspector = sa.inspect(op.get_bind())
    existing = {
        item["name"]
        for item in inspector.get_indexes("connector_sync_cursors")
        if item.get("name")
    }
    if "ix_connector_sync_cursor_tenant_provider" not in existing:
        op.create_index(
            "ix_connector_sync_cursor_tenant_provider",
            "connector_sync_cursors",
            ["tenant_id", "provider"],
            unique=False,
        )
    if "ix_connector_sync_cursor_status" not in existing:
        op.create_index(
            "ix_connector_sync_cursor_status",
            "connector_sync_cursors",
            ["status", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    # Production connector cursor history is intentionally not destroyed by an
    # automatic downgrade. Rollback requires an explicit operator migration.
    pass

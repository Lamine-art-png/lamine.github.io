"""Add durable task outbox for Redis Streams publication.

Revision ID: 013_task_outbox
Revises: 012_connector_security
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "013_task_outbox"
down_revision = "012_connector_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "task_outbox" not in inspector.get_table_names():
        op.create_table(
            "task_outbox",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("job_id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("publish_attempts", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", name="uq_task_outbox_job"),
        )
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes("task_outbox") if item.get("name")}
    if "ix_task_outbox_pending" not in existing:
        op.create_index("ix_task_outbox_pending", "task_outbox", ["status", "next_attempt_at", "created_at"], unique=False)
    if "ix_task_outbox_tenant" not in existing:
        op.create_index("ix_task_outbox_tenant", "task_outbox", ["tenant_id"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "task_outbox" in inspector.get_table_names():
        op.drop_table("task_outbox")

"""Field Intelligence launch control plane.

Revision ID: 027_field_intelligence_launch
Revises: 026_platform_api_operations
Create Date: 2026-07-19

Adds the two small operational tables the controlled rollout needs:

* ``field_runtime_flags`` — server-authoritative runtime controls (emergency
  kill switch, rollout overrides). Deployment configuration remains the source
  of the *default* release state; flags provide immediate, audited emergency
  control without a redeploy.
* ``field_worker_heartbeats`` — one row per live worker instance so readiness,
  queue-health and exact-SHA release alignment can be proven from the database
  the workers actually use.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "027_field_intelligence_launch"
down_revision = "026_platform_api_operations"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def upgrade() -> None:
    if not _has_table("field_runtime_flags"):
        op.create_table(
            "field_runtime_flags",
            sa.Column("key", sa.String(length=120), primary_key=True),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _has_table("field_worker_heartbeats"):
        op.create_table(
            "field_worker_heartbeats",
            sa.Column("worker_id", sa.String(length=120), primary_key=True),
            sa.Column("hostname", sa.String(), nullable=True),
            sa.Column("git_sha", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
            sa.Column("last_tick_json", sa.JSON(), nullable=True),
        )
        op.create_index(
            "ix_field_worker_heartbeats_seen", "field_worker_heartbeats", ["last_heartbeat_at"]
        )


def downgrade() -> None:
    for table in ("field_worker_heartbeats", "field_runtime_flags"):
        if _has_table(table):
            op.drop_table(table)

"""Add deterministic agent workflow layer.

Revision ID: 005_agent_workflow_layer
Revises: 004_assurance_audit_mvp
Create Date: 2026-06-22 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "005_agent_workflow_layer"
down_revision = "004_assurance_audit_mvp"
branch_labels = None
depends_on = None


TABLES = [
    "agent_workflow_runs",
    "agent_tasks",
    "agent_findings",
    "agent_recommendations",
    "agent_action_proposals",
    "agent_tool_calls",
    "agent_messages",
    "agent_run_audit_events",
]


def _common_columns(include_run: bool) -> list[sa.Column]:
    columns = [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    ]
    if include_run:
        columns.append(sa.Column("run_id", sa.String(), sa.ForeignKey("agent_workflow_runs.id"), nullable=False, index=True))
    columns.extend([
        sa.Column("passport_id", sa.String(), sa.ForeignKey("assurance_passports.id"), nullable=True, index=True),
        sa.Column("workbench_session_id", sa.String(), nullable=True, index=True),
        sa.Column("workflow_type", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("priority", sa.String(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("actor", sa.String(), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False, index=True),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    ])
    return columns


def upgrade() -> None:
    op.create_table("agent_workflow_runs", *_common_columns(include_run=False))
    for table in TABLES[1:]:
        op.create_table(table, *_common_columns(include_run=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)


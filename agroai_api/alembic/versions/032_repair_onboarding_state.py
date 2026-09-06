"""Repair production onboarding_states schema drift.

Revision ID: 032_repair_onboarding_state
Revises: 031_merge_assurance_intelligence
Create Date: 2026-09-05

Production was observed at the repository Alembic head while the historical
onboarding_states table from revision 007 was absent. This forward-only repair
restores the required table without rewriting shipped migration history.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "032_repair_onboarding_state"
down_revision = "031_merge_assurance_intelligence"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _create_index(name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    if not _has_table("onboarding_states"):
        op.create_table(
            "onboarding_states",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("current_step", sa.String(), nullable=False),
            sa.Column("selected_plan", sa.String(), nullable=True),
            sa.Column("organization_type", sa.String(), nullable=True),
            sa.Column("acres_or_sites", sa.String(), nullable=True),
            sa.Column("primary_goal", sa.String(), nullable=True),
            sa.Column("completed_steps_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_onboarding_org_user"),
        )

    for name, columns in {
        "ix_onboarding_states_id": ["id"],
        "ix_onboarding_states_organization_id": ["organization_id"],
        "ix_onboarding_states_workspace_id": ["workspace_id"],
        "ix_onboarding_states_user_id": ["user_id"],
        "ix_onboarding_states_created_at": ["created_at"],
    }.items():
        _create_index(name, "onboarding_states", columns)


def downgrade() -> None:
    # Do not remove a table that belongs to historical revision 007.
    # This repair revision is intentionally non-destructive.
    pass

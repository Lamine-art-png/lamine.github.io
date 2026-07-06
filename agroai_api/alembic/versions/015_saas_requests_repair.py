"""Repair the SaaS request table required by the production portal.

Revision ID: 015_saas_requests_repair
Revises: 014_connector_sync_cursors
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "015_saas_requests_repair"
down_revision = "014_connector_sync_cursors"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _add_missing_column(name: str, column: sa.Column) -> None:
    if name not in _columns("saas_requests"):
        op.add_column("saas_requests", column)


def _create_index(name: str, columns: list[str]) -> None:
    inspector = _inspector()
    existing = {item.get("name") for item in inspector.get_indexes("saas_requests")}
    if name not in existing and set(columns).issubset(_columns("saas_requests")):
        op.create_index(name, "saas_requests", columns, unique=False)


def upgrade() -> None:
    inspector = _inspector()
    if "saas_requests" not in inspector.get_table_names():
        op.create_table(
            "saas_requests",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=True),
            sa.Column("workspace_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("priority", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("company", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("source_page", sa.String(), nullable=True),
            sa.Column("notification_status", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        # Existing deployments may have a partially adopted table. Additive repair
        # keeps data intact and allows Alembic to converge the runtime contract.
        _add_missing_column("id", sa.Column("id", sa.String(), nullable=True))
        _add_missing_column("organization_id", sa.Column("organization_id", sa.String(), nullable=True))
        _add_missing_column("workspace_id", sa.Column("workspace_id", sa.String(), nullable=True))
        _add_missing_column("user_id", sa.Column("user_id", sa.String(), nullable=True))
        _add_missing_column("type", sa.Column("type", sa.String(), nullable=False, server_default="support"))
        _add_missing_column("status", sa.Column("status", sa.String(), nullable=False, server_default="received"))
        _add_missing_column("priority", sa.Column("priority", sa.String(), nullable=False, server_default="medium"))
        _add_missing_column("name", sa.Column("name", sa.String(), nullable=True))
        _add_missing_column("email", sa.Column("email", sa.String(), nullable=True))
        _add_missing_column("company", sa.Column("company", sa.String(), nullable=True))
        _add_missing_column("role", sa.Column("role", sa.String(), nullable=True))
        _add_missing_column("subject", sa.Column("subject", sa.String(), nullable=False, server_default=""))
        _add_missing_column("message", sa.Column("message", sa.String(), nullable=False, server_default=""))
        _add_missing_column("source_page", sa.Column("source_page", sa.String(), nullable=True))
        _add_missing_column("notification_status", sa.Column("notification_status", sa.String(), nullable=False, server_default="stored"))
        _add_missing_column("metadata_json", sa.Column("metadata_json", sa.JSON(), nullable=True))
        _add_missing_column("created_at", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
        _add_missing_column("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))

    for name, columns in {
        "ix_saas_requests_id": ["id"],
        "ix_saas_requests_organization_id": ["organization_id"],
        "ix_saas_requests_workspace_id": ["workspace_id"],
        "ix_saas_requests_user_id": ["user_id"],
        "ix_saas_requests_type": ["type"],
        "ix_saas_requests_status": ["status"],
        "ix_saas_requests_priority": ["priority"],
        "ix_saas_requests_created_at": ["created_at"],
    }.items():
        _create_index(name, columns)


def downgrade() -> None:
    # Request history is customer data. Automated downgrade intentionally keeps it.
    pass

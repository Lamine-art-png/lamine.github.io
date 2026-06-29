"""Add SaaS portal v2.1 verification and team invitation tables.

Revision ID: 008_saas_portal_v2_1_security
Revises: 007_saas_portal_v2
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = "008_saas_portal_v2_1_security"
down_revision = "007_saas_portal_v2"
branch_labels = None
depends_on = None


# Render starts the API with:
#   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
#
# This migration must finish quickly before Uvicorn can bind Render's port.
# Keep it intentionally online-safe: no foreign-key creation, no index DDL, and
# no table rewrites. Add stricter constraints/indexes later in a separate
# post-deploy migration after the service is healthy.


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _has_table("users") and not _has_column("users", "email_verified_at"):
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    if _has_table("users") and not _has_column("users", "email_verification_status"):
        op.add_column(
            "users",
            sa.Column("email_verification_status", sa.String(), nullable=True, server_default="unverified"),
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL,
            token_hash VARCHAR NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_invitations (
            id VARCHAR PRIMARY KEY,
            organization_id VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            invited_by_user_id VARCHAR NOT NULL,
            token_hash VARCHAR UNIQUE,
            expires_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_invitations")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")
    if _has_table("users") and _has_column("users", "email_verification_status"):
        op.drop_column("users", "email_verification_status")
    if _has_table("users") and _has_column("users", "email_verified_at"):
        op.drop_column("users", "email_verified_at")

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


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _create_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    existing = {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if _has_table("users") and not _has_column("users", "email_verified_at"):
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    if _has_table("users") and not _has_column("users", "email_verification_status"):
        op.add_column("users", sa.Column("email_verification_status", sa.String(), nullable=False, server_default="unverified"))
    if _has_table("users"):
        _create_index("ix_users_email_verification_status", "users", ["email_verification_status"])

    if not _has_table("email_verification_tokens"):
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
    for name, columns, unique in [
        ("ix_email_verification_tokens_id", ["id"], False),
        ("ix_email_verification_tokens_user_id", ["user_id"], False),
        ("ix_email_verification_tokens_token_hash", ["token_hash"], True),
        ("ix_email_verification_tokens_expires_at", ["expires_at"], False),
        ("ix_email_verification_tokens_created_at", ["created_at"], False),
    ]:
        _create_index(name, "email_verification_tokens", columns, unique=unique)

    if not _has_table("team_invitations"):
        op.create_table(
            "team_invitations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("invited_by_user_id", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
    for name, columns, unique in [
        ("ix_team_invitations_id", ["id"], False),
        ("ix_team_invitations_organization_id", ["organization_id"], False),
        ("ix_team_invitations_email", ["email"], False),
        ("ix_team_invitations_status", ["status"], False),
        ("ix_team_invitations_invited_by_user_id", ["invited_by_user_id"], False),
        ("ix_team_invitations_token_hash", ["token_hash"], True),
        ("ix_team_invitations_created_at", ["created_at"], False),
    ]:
        _create_index(name, "team_invitations", columns, unique=unique)


def downgrade() -> None:
    op.drop_table("team_invitations")
    op.drop_table("email_verification_tokens")
    op.drop_index("ix_users_email_verification_status", table_name="users")
    op.drop_column("users", "email_verification_status")
    op.drop_column("users", "email_verified_at")

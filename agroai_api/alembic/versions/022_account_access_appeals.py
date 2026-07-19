"""Add secure account access appeals and restrict selected legacy accounts.

Revision ID: 022_account_access_appeals
Revises: 021_platform_api_hardening
Create Date: 2026-07-19
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "022_account_access_appeals"
down_revision = "021_platform_api_hardening"
branch_labels = None
depends_on = None

TARGET_EMAILS = (
    "emmanuel.ahoa@wur.nl",
    "apoorvakaushal.2001@gmail.com",
    "hichemabidiaz@gmail.com",
    "omt91560@gmail.com",
    "a.heckmann@agvolution.com",
    "geraldjtb@gmail.com",
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    if table not in _inspector().get_table_names():
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _inspector().get_table_names():
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _add_column("users", sa.Column("access_restriction_reason", sa.String(), nullable=True))
    _add_column("users", sa.Column("access_restricted_at", sa.DateTime(), nullable=True))
    _add_column("users", sa.Column("access_restriction_notified_at", sa.DateTime(), nullable=True))
    _create_index("ix_users_access_restriction_reason", "users", ["access_restriction_reason"])
    _create_index("ix_users_access_restricted_at", "users", ["access_restricted_at"])

    if "account_access_appeals" not in _inspector().get_table_names():
        op.create_table(
            "account_access_appeals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("token_expires_at", sa.DateTime(), nullable=False),
            sa.Column("token_used_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="link_sent"),
            sa.Column("full_name", sa.String(), nullable=True),
            sa.Column("professional_role", sa.String(), nullable=True),
            sa.Column("organization_name", sa.String(), nullable=True),
            sa.Column("website_url", sa.String(), nullable=True),
            sa.Column("professional_profile_url", sa.String(), nullable=True),
            sa.Column("agricultural_use_case", sa.Text(), nullable=True),
            sa.Column("acres_or_sites", sa.String(), nullable=True),
            sa.Column("planned_data_sources", sa.Text(), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("supporting_evidence_url", sa.String(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("token_hash", name="uq_account_access_appeals_token_hash"),
        )
    for name, columns, unique in (
        ("ix_account_access_appeals_user_id", ["user_id"], False),
        ("ix_account_access_appeals_organization_id", ["organization_id"], False),
        ("ix_account_access_appeals_token_hash", ["token_hash"], True),
        ("ix_account_access_appeals_token_expires_at", ["token_expires_at"], False),
        ("ix_account_access_appeals_status", ["status"], False),
        ("ix_account_access_appeals_submitted_at", ["submitted_at"], False),
        ("ix_account_access_appeals_reviewed_at", ["reviewed_at"], False),
        ("ix_account_access_appeals_reviewed_by_user_id", ["reviewed_by_user_id"], False),
        ("ix_account_access_appeals_created_at", ["created_at"], False),
    ):
        _create_index(name, "account_access_appeals", columns, unique=unique)

    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.String()),
        sa.column("email", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("account_status", sa.String()),
        sa.column("credentials_changed_at", sa.DateTime()),
        sa.column("access_restriction_reason", sa.String()),
        sa.column("access_restricted_at", sa.DateTime()),
    )
    organizations = sa.table(
        "organizations",
        sa.column("owner_user_id", sa.String()),
        sa.column("verification_status", sa.String()),
        sa.column("verification_reason_codes_json", sa.JSON()),
        sa.column("verified_at", sa.DateTime()),
    )
    ids = [row[0] for row in bind.execute(sa.select(users.c.id).where(sa.func.lower(users.c.email).in_(TARGET_EMAILS))).all()]
    if ids:
        now = datetime.utcnow()
        bind.execute(
            users.update().where(users.c.id.in_(ids)).values(
                is_active=False,
                account_status="suspended_pending_appeal",
                credentials_changed_at=now,
                access_restriction_reason="legacy_organization_reverification_required",
                access_restricted_at=now,
            )
        )
        bind.execute(
            organizations.update().where(organizations.c.owner_user_id.in_(ids)).values(
                verification_status="suspended_pending_appeal",
                verification_reason_codes_json=["legacy_organization_reverification_required"],
                verified_at=None,
            )
        )


def downgrade() -> None:
    if "account_access_appeals" in _inspector().get_table_names():
        op.drop_table("account_access_appeals")
    for index_name in ("ix_users_access_restricted_at", "ix_users_access_restriction_reason"):
        if index_name in _indexes("users"):
            op.drop_index(index_name, table_name="users")
    for column_name in ("access_restriction_notified_at", "access_restricted_at", "access_restriction_reason"):
        if column_name in _columns("users"):
            op.drop_column("users", column_name)

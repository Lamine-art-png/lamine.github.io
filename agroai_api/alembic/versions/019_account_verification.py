"""Add automated organization verification and auth security controls.

Revision ID: 019_account_verification
Revises: 018_outreach_engagement
Create Date: 2026-07-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "019_account_verification"
down_revision = "018_outreach_engagement"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _add_column("users", sa.Column("account_status", sa.String(), nullable=False, server_default="active"))
    _add_column("users", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
    _add_column("users", sa.Column("failed_login_window_started_at", sa.DateTime(), nullable=True))
    _add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))
    _create_index("ix_users_account_status", "users", ["account_status"])
    _create_index("ix_users_locked_until", "users", ["locked_until"])

    _add_column("organizations", sa.Column("verification_status", sa.String(), nullable=False, server_default="approved_legacy"))
    _add_column("organizations", sa.Column("verification_score", sa.Integer(), nullable=True))
    _add_column("organizations", sa.Column("verification_reason_codes_json", sa.JSON(), nullable=True))
    _add_column("organizations", sa.Column("verification_engine_version", sa.String(), nullable=True))
    _add_column("organizations", sa.Column("verification_submitted_at", sa.DateTime(), nullable=True))
    _add_column("organizations", sa.Column("verified_at", sa.DateTime(), nullable=True))
    _create_index("ix_organizations_verification_status", "organizations", ["verification_status"])

    if not _has_table("organization_verification_profiles"):
        op.create_table(
            "organization_verification_profiles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), nullable=False),
            sa.Column("professional_role", sa.String(), nullable=False),
            sa.Column("organization_type", sa.String(), nullable=False),
            sa.Column("website_url", sa.String(), nullable=True),
            sa.Column("professional_profile_url", sa.String(), nullable=True),
            sa.Column("country", sa.String(), nullable=False),
            sa.Column("operating_region", sa.String(), nullable=False),
            sa.Column("acres_or_sites", sa.String(), nullable=False),
            sa.Column("primary_crops", sa.String(), nullable=False),
            sa.Column("intended_use", sa.Text(), nullable=False),
            sa.Column("planned_data_sources", sa.Text(), nullable=False),
            sa.Column("email_domain", sa.String(), nullable=False),
            sa.Column("domain_classification", sa.String(), nullable=False),
            sa.Column("phone_algorithm", sa.String(), nullable=False),
            sa.Column("phone_key_version", sa.String(), nullable=False),
            sa.Column("phone_nonce_b64", sa.Text(), nullable=False),
            sa.Column("phone_ciphertext_b64", sa.Text(), nullable=False),
            sa.Column("phone_last4", sa.String(length=4), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("reason_codes_json", sa.JSON(), nullable=True),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("evidence_digest", sa.String(length=64), nullable=False),
            sa.Column("submitted_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("organization_id", name="uq_org_verification_profile_org"),
        )
    _create_index("ix_org_verification_profiles_org", "organization_verification_profiles", ["organization_id"], unique=True)
    _create_index("ix_org_verification_profiles_type", "organization_verification_profiles", ["organization_type"])
    _create_index("ix_org_verification_profiles_country", "organization_verification_profiles", ["country"])
    _create_index("ix_org_verification_profiles_email_domain", "organization_verification_profiles", ["email_domain"])
    _create_index("ix_org_verification_profiles_domain_class", "organization_verification_profiles", ["domain_classification"])
    _create_index("ix_org_verification_profiles_decision", "organization_verification_profiles", ["decision"])
    _create_index("ix_org_verification_profiles_digest", "organization_verification_profiles", ["evidence_digest"])
    _create_index("ix_org_verification_profiles_submitted", "organization_verification_profiles", ["submitted_at"])

    if not _has_table("security_audit_events"):
        op.create_table(
            "security_audit_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("organization_id", sa.String(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("outcome", sa.String(), nullable=False),
            sa.Column("subject_hash", sa.String(length=64), nullable=True),
            sa.Column("ip_hash", sa.String(length=64), nullable=True),
            sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
    _create_index("ix_security_audit_events_org", "security_audit_events", ["organization_id"])
    _create_index("ix_security_audit_events_user", "security_audit_events", ["user_id"])
    _create_index("ix_security_audit_events_type", "security_audit_events", ["event_type"])
    _create_index("ix_security_audit_events_outcome", "security_audit_events", ["outcome"])
    _create_index("ix_security_audit_events_subject", "security_audit_events", ["subject_hash"])
    _create_index("ix_security_audit_events_ip", "security_audit_events", ["ip_hash"])
    _create_index("ix_security_audit_events_created", "security_audit_events", ["created_at"])


def downgrade() -> None:
    if _has_table("security_audit_events"):
        op.drop_table("security_audit_events")
    if _has_table("organization_verification_profiles"):
        op.drop_table("organization_verification_profiles")

    for index_name in ("ix_organizations_verification_status",):
        if index_name in _indexes("organizations"):
            op.drop_index(index_name, table_name="organizations")
    for column_name in (
        "verified_at",
        "verification_submitted_at",
        "verification_engine_version",
        "verification_reason_codes_json",
        "verification_score",
        "verification_status",
    ):
        if column_name in _columns("organizations"):
            op.drop_column("organizations", column_name)

    for index_name in ("ix_users_locked_until", "ix_users_account_status"):
        if index_name in _indexes("users"):
            op.drop_index(index_name, table_name="users")
    for column_name in (
        "locked_until",
        "failed_login_window_started_at",
        "failed_login_attempts",
        "account_status",
    ):
        if column_name in _columns("users"):
            op.drop_column("users", column_name)

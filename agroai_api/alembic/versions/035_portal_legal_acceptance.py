"""Add immutable Enterprise Portal signup legal acceptance records.

Revision ID: 035_portal_legal_acceptance
Revises: 034_intelligence_wallet_commerce
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "035_portal_legal_acceptance"
down_revision = "034_intelligence_wallet_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_legal_acceptances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organization_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column("terms_url", sa.String(), nullable=False),
        sa.Column("privacy_version", sa.String(), nullable=False),
        sa.Column("privacy_url", sa.String(), nullable=False),
        sa.Column("acceptance_text", sa.Text(), nullable=False),
        sa.Column("acceptance_text_hash", sa.String(length=64), nullable=False),
        sa.Column("document_bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("authority_confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(), nullable=False, server_default="signup"),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "terms_version",
            "privacy_version",
            name="uq_portal_legal_acceptance_version",
        ),
    )
    op.create_index("ix_portal_legal_acceptances_org", "portal_legal_acceptances", ["organization_id"])
    op.create_index("ix_portal_legal_acceptances_user", "portal_legal_acceptances", ["user_id"])
    op.create_index("ix_portal_legal_acceptances_email", "portal_legal_acceptances", ["email"])
    op.create_index("ix_portal_legal_acceptances_bundle", "portal_legal_acceptances", ["document_bundle_hash"])
    op.create_index("ix_portal_legal_acceptances_accepted", "portal_legal_acceptances", ["accepted_at"])


def downgrade() -> None:
    op.drop_index("ix_portal_legal_acceptances_accepted", table_name="portal_legal_acceptances")
    op.drop_index("ix_portal_legal_acceptances_bundle", table_name="portal_legal_acceptances")
    op.drop_index("ix_portal_legal_acceptances_email", table_name="portal_legal_acceptances")
    op.drop_index("ix_portal_legal_acceptances_user", table_name="portal_legal_acceptances")
    op.drop_index("ix_portal_legal_acceptances_org", table_name="portal_legal_acceptances")
    op.drop_table("portal_legal_acceptances")

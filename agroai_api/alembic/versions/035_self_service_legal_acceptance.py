"""Add self-service clickwrap acceptance ledger.

Revision ID: 035_self_service_legal_acceptance
Revises: 034_intelligence_wallet_commerce
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "035_self_service_legal_acceptance"
down_revision = "034_intelligence_wallet_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "self_service_legal_acceptances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column("privacy_version", sa.String(), nullable=False),
        sa.Column("terms_url", sa.String(), nullable=False),
        sa.Column("privacy_url", sa.String(), nullable=False),
        sa.Column("acceptance_text", sa.Text(), nullable=False),
        sa.Column("authority_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "terms_version",
            "privacy_version",
            name="uq_self_service_legal_acceptance_versions",
        ),
    )
    op.create_index("ix_self_service_legal_acceptances_org", "self_service_legal_acceptances", ["organization_id"])
    op.create_index("ix_self_service_legal_acceptances_user", "self_service_legal_acceptances", ["user_id"])
    op.create_index("ix_self_service_legal_acceptances_terms", "self_service_legal_acceptances", ["terms_version"])
    op.create_index("ix_self_service_legal_acceptances_privacy", "self_service_legal_acceptances", ["privacy_version"])
    op.create_index("ix_self_service_legal_acceptances_ip_hash", "self_service_legal_acceptances", ["ip_hash"])
    op.create_index("ix_self_service_legal_acceptances_accepted_at", "self_service_legal_acceptances", ["accepted_at"])


def downgrade() -> None:
    op.drop_index("ix_self_service_legal_acceptances_accepted_at", table_name="self_service_legal_acceptances")
    op.drop_index("ix_self_service_legal_acceptances_ip_hash", table_name="self_service_legal_acceptances")
    op.drop_index("ix_self_service_legal_acceptances_privacy", table_name="self_service_legal_acceptances")
    op.drop_index("ix_self_service_legal_acceptances_terms", table_name="self_service_legal_acceptances")
    op.drop_index("ix_self_service_legal_acceptances_user", table_name="self_service_legal_acceptances")
    op.drop_index("ix_self_service_legal_acceptances_org", table_name="self_service_legal_acceptances")
    op.drop_table("self_service_legal_acceptances")

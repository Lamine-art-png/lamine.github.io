"""Add Enterprise Portal customer clickwrap acceptance ledger.

Revision ID: 035_customer_legal_acceptance
Revises: 034_intelligence_wallet_commerce
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "035_customer_legal_acceptance"
down_revision = "034_intelligence_wallet_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_legal_acceptances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_email", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column("privacy_version", sa.String(), nullable=False),
        sa.Column("terms_effective_date", sa.String(), nullable=False),
        sa.Column("privacy_effective_date", sa.String(), nullable=False),
        sa.Column("terms_url", sa.String(), nullable=False),
        sa.Column("privacy_url", sa.String(), nullable=False),
        sa.Column("terms_reference_digest", sa.String(length=64), nullable=False),
        sa.Column("privacy_reference_digest", sa.String(length=64), nullable=False),
        sa.Column("acceptance_text", sa.Text(), nullable=False),
        sa.Column("accepted_terms", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_privacy", sa.Boolean(), nullable=False),
        sa.Column("authority_confirmed", sa.Boolean(), nullable=False),
        sa.Column("order_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_legal_acceptance_org_time", "customer_legal_acceptances", ["organization_id", "accepted_at"])
    op.create_index("ix_customer_legal_acceptance_user_time", "customer_legal_acceptances", ["user_id", "accepted_at"])
    op.create_index("ix_customer_legal_acceptance_versions", "customer_legal_acceptances", ["terms_version", "privacy_version", "accepted_at"])
    op.create_index("ix_customer_legal_acceptances_organization_id", "customer_legal_acceptances", ["organization_id"])
    op.create_index("ix_customer_legal_acceptances_user_id", "customer_legal_acceptances", ["user_id"])
    op.create_index("ix_customer_legal_acceptances_event_type", "customer_legal_acceptances", ["event_type"])
    op.create_index("ix_customer_legal_acceptances_request_id", "customer_legal_acceptances", ["request_id"])
    op.create_index("ix_customer_legal_acceptances_accepted_at", "customer_legal_acceptances", ["accepted_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_legal_acceptances_accepted_at", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptances_request_id", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptances_event_type", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptances_user_id", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptances_organization_id", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptance_versions", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptance_user_time", table_name="customer_legal_acceptances")
    op.drop_index("ix_customer_legal_acceptance_org_time", table_name="customer_legal_acceptances")
    op.drop_table("customer_legal_acceptances")

"""Add prepaid intelligence wallet and commercial intelligence runs.

Revision ID: 033_intelligence_wallet_commerce
Revises: 032_repair_onboarding_state
Create Date: 2026-09-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "033_intelligence_wallet_commerce"
down_revision = "032_repair_onboarding_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_intelligence_wallets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="usd"),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_funded_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_spent_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_reload_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_reload_threshold_cents", sa.Integer(), nullable=True),
        sa.Column("auto_reload_amount_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_platform_intelligence_wallet_org"),
    )
    op.create_index("ix_platform_intelligence_wallet_org", "platform_intelligence_wallets", ["organization_id"], unique=True)

    op.create_table(
        "platform_intelligence_wallet_ledger",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wallet_id", sa.String(), sa.ForeignKey("platform_intelligence_wallets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(), nullable=True),
        sa.Column("intelligence_run_id", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_intelligence_wallet_ledger_idempotency"),
        sa.UniqueConstraint("external_reference", name="uq_intelligence_wallet_ledger_external_reference"),
    )
    op.create_index("ix_intelligence_wallet_ledger_org_time", "platform_intelligence_wallet_ledger", ["organization_id", "created_at"])
    op.create_index("ix_intelligence_wallet_ledger_status", "platform_intelligence_wallet_ledger", ["status", "created_at"])
    op.create_index("ix_intelligence_wallet_ledger_wallet", "platform_intelligence_wallet_ledger", ["wallet_id"])
    op.create_index("ix_intelligence_wallet_ledger_run", "platform_intelligence_wallet_ledger", ["intelligence_run_id"])

    op.create_table(
        "platform_commercial_intelligence_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_project_id", sa.String(), sa.ForeignKey("api_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.String(), sa.ForeignKey("platform_api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("public_model", sa.String(), nullable=False, server_default="agroai-intelligence-1"),
        sa.Column("status", sa.String(), nullable=False, server_default="processing"),
        sa.Column("charge_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="usd"),
        sa.Column("request_safe_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("provider_internal", sa.String(), nullable=True),
        sa.Column("model_internal", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "api_project_id", "idempotency_key", name="uq_commercial_intelligence_run_idempotency"),
    )
    op.create_index("ix_commercial_intelligence_run_org_time", "platform_commercial_intelligence_runs", ["organization_id", "created_at"])
    op.create_index("ix_commercial_intelligence_run_project_time", "platform_commercial_intelligence_runs", ["api_project_id", "created_at"])
    op.create_index("ix_commercial_intelligence_run_status", "platform_commercial_intelligence_runs", ["status", "created_at"])
    op.create_index("ix_commercial_intelligence_run_key", "platform_commercial_intelligence_runs", ["api_key_id"])


def downgrade() -> None:
    op.drop_index("ix_commercial_intelligence_run_key", table_name="platform_commercial_intelligence_runs")
    op.drop_index("ix_commercial_intelligence_run_status", table_name="platform_commercial_intelligence_runs")
    op.drop_index("ix_commercial_intelligence_run_project_time", table_name="platform_commercial_intelligence_runs")
    op.drop_index("ix_commercial_intelligence_run_org_time", table_name="platform_commercial_intelligence_runs")
    op.drop_table("platform_commercial_intelligence_runs")
    op.drop_index("ix_intelligence_wallet_ledger_run", table_name="platform_intelligence_wallet_ledger")
    op.drop_index("ix_intelligence_wallet_ledger_wallet", table_name="platform_intelligence_wallet_ledger")
    op.drop_index("ix_intelligence_wallet_ledger_status", table_name="platform_intelligence_wallet_ledger")
    op.drop_index("ix_intelligence_wallet_ledger_org_time", table_name="platform_intelligence_wallet_ledger")
    op.drop_table("platform_intelligence_wallet_ledger")
    op.drop_index("ix_platform_intelligence_wallet_org", table_name="platform_intelligence_wallets")
    op.drop_table("platform_intelligence_wallets")

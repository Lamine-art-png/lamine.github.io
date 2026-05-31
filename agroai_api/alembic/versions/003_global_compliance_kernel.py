"""global compliance kernel v2

Revision ID: 003_global_compliance_kernel
Revises: 002_california_compliance_pack
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "003_global_compliance_kernel"
down_revision = "002_california_compliance_pack"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name, column):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column.name not in existing:
        op.add_column(table_name, column)


def _create_index_if_missing(index_name, table_name, columns):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def upgrade():
    _add_column_if_missing("compliance_jurisdictions", sa.Column("country_code", sa.String(), nullable=False, server_default="US"))
    _add_column_if_missing("compliance_jurisdictions", sa.Column("region_name", sa.String(), nullable=True))
    _add_column_if_missing("compliance_jurisdictions", sa.Column("authority_name", sa.String(), nullable=True))
    _add_column_if_missing("compliance_jurisdictions", sa.Column("pack_version", sa.String(), nullable=True))
    _add_column_if_missing("compliance_jurisdictions", sa.Column("legal_review_status", sa.String(), nullable=False, server_default="pending_legal_review"))
    _add_column_if_missing("compliance_jurisdictions", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("compliance_execution_ledger", sa.Column("ledger_payload", sa.JSON(), nullable=True))
    _add_column_if_missing("compliance_rule_packs", sa.Column("country_code", sa.String(), nullable=False, server_default="US"))
    _add_column_if_missing("compliance_rule_packs", sa.Column("authority_name", sa.String(), nullable=True))
    _add_column_if_missing("compliance_rule_packs", sa.Column("legal_review_status", sa.String(), nullable=False, server_default="pending_legal_review"))
    _add_column_if_missing("compliance_rule_packs", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "compliance_exports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_type", sa.String(), nullable=False),
        sa.Column("export_type", sa.String(), nullable=False),
        sa.Column("readiness_status", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("storage_backend", sa.String(), nullable=False, server_default="database_dev_fallback"),
        sa.Column("storage_ref", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_base64", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    _create_index_if_missing("ix_compliance_jurisdictions_country_code", "compliance_jurisdictions", ["country_code"])
    _create_index_if_missing("ix_compliance_jurisdictions_region_name", "compliance_jurisdictions", ["region_name"])
    _create_index_if_missing("ix_compliance_jurisdictions_legal_review_status", "compliance_jurisdictions", ["legal_review_status"])
    _create_index_if_missing("ix_compliance_jurisdictions_enabled", "compliance_jurisdictions", ["enabled"])
    _create_index_if_missing("ix_compliance_rule_packs_country_code", "compliance_rule_packs", ["country_code"])
    _create_index_if_missing("ix_compliance_rule_packs_legal_review_status", "compliance_rule_packs", ["legal_review_status"])
    _create_index_if_missing("ix_compliance_exports_tenant_id", "compliance_exports", ["tenant_id"])
    _create_index_if_missing("ix_compliance_exports_workflow_type", "compliance_exports", ["workflow_type"])
    _create_index_if_missing("ix_compliance_exports_export_type", "compliance_exports", ["export_type"])
    _create_index_if_missing("ix_compliance_exports_readiness_status", "compliance_exports", ["readiness_status"])
    _create_index_if_missing("ix_compliance_exports_storage_backend", "compliance_exports", ["storage_backend"])
    _create_index_if_missing("ix_compliance_exports_checksum_sha256", "compliance_exports", ["checksum_sha256"])
    _create_index_if_missing("ix_compliance_export_tenant_type", "compliance_exports", ["tenant_id", "export_type", "created_at"])


def downgrade():
    op.drop_table("compliance_exports")
    # Non-destructive rollout columns are intentionally left in place on downgrade.

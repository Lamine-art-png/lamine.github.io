"""global compliance kernel

Revision ID: 003_global_compliance_kernel
Revises: 002_california_compliance_pack
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "003_global_compliance_kernel"
down_revision = "002_california_compliance_pack"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name):
    return table_name in inspector.get_table_names()


def _columns(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector, table_name, index_name):
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _create_index_if_missing(bind, table_name, index_name, columns):
    inspector = sa.inspect(bind)
    if _has_table(inspector, table_name) and not _has_index(inspector, table_name, index_name):
        existing_cols = _columns(inspector, table_name)
        if all(column in existing_cols for column in columns):
            op.create_index(index_name, table_name, columns)


def _has_unique(inspector, table_name, columns):
    wanted = tuple(columns)
    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or []) == wanted:
            return True
    return False


def _flex_workflow_column(bind, table_name, nullable=False):
    inspector = sa.inspect(bind)
    if not _has_table(inspector, table_name) or "workflow_type" not in _columns(inspector, table_name):
        return
    with op.batch_alter_table(table_name) as batch:
        if bind.dialect.name == "postgresql":
            batch.alter_column("workflow_type", type_=sa.String(length=128), postgresql_using="workflow_type::text", nullable=nullable)
        else:
            batch.alter_column("workflow_type", existing_type=sa.String(length=64), type_=sa.String(length=128), nullable=nullable)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "compliance_jurisdictions"):
        cols = _columns(inspector, "compliance_jurisdictions")
        with op.batch_alter_table("compliance_jurisdictions") as batch:
            if "country" not in cols:
                batch.add_column(sa.Column("country", sa.String(), nullable=True))
            if "jurisdiction_level" not in cols:
                batch.add_column(sa.Column("jurisdiction_level", sa.String(), nullable=True))
            if "authority_name" not in cols:
                batch.add_column(sa.Column("authority_name", sa.String(), nullable=True))
            if "state" in cols:
                batch.alter_column("state", existing_type=sa.String(), nullable=True)
            if "county" in cols:
                batch.alter_column("county", existing_type=sa.String(), nullable=True)

    _flex_workflow_column(bind, "compliance_jurisdictions", nullable=False)
    _flex_workflow_column(bind, "compliance_rule_packs", nullable=False)
    _flex_workflow_column(bind, "compliance_readiness_snapshots", nullable=False)
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS compliance_workflow_type")

    _create_index_if_missing(bind, "compliance_jurisdictions", "ix_compliance_jurisdictions_country", ["country"])
    _create_index_if_missing(bind, "compliance_jurisdictions", "ix_compliance_jurisdictions_jurisdiction_level", ["jurisdiction_level"])
    _create_index_if_missing(bind, "compliance_jurisdictions", "ix_compliance_jurisdictions_authority_name", ["authority_name"])

    if _has_table(inspector, "compliance_parcels"):
        cols = _columns(inspector, "compliance_parcels")
        with op.batch_alter_table("compliance_parcels") as batch:
            if "parcel_identifier" not in cols:
                batch.add_column(sa.Column("parcel_identifier", sa.String(), nullable=True))
            if "country" not in cols:
                batch.add_column(sa.Column("country", sa.String(), nullable=True))
            if "state" not in cols:
                batch.add_column(sa.Column("state", sa.String(), nullable=True))
            if "apn" in cols:
                batch.alter_column("apn", existing_type=sa.String(), nullable=True)
            if "county" in cols:
                batch.alter_column("county", existing_type=sa.String(), nullable=True)
        op.execute("UPDATE compliance_parcels SET parcel_identifier = apn WHERE parcel_identifier IS NULL")
        inspector = sa.inspect(bind)
        with op.batch_alter_table("compliance_parcels") as batch:
            batch.alter_column("parcel_identifier", existing_type=sa.String(), nullable=False)
            if not _has_unique(inspector, "compliance_parcels", ["tenant_id", "parcel_identifier"]):
                batch.create_unique_constraint("uq_compliance_parcel_tenant_identifier", ["tenant_id", "parcel_identifier"])

    _create_index_if_missing(bind, "compliance_parcels", "ix_compliance_parcels_parcel_identifier", ["parcel_identifier"])
    _create_index_if_missing(bind, "compliance_parcels", "ix_compliance_parcels_country", ["country"])
    _create_index_if_missing(bind, "compliance_parcels", "ix_compliance_parcels_state", ["state"])

    if _has_table(inspector, "compliance_wells"):
        cols = _columns(inspector, "compliance_wells")
        with op.batch_alter_table("compliance_wells") as batch:
            if "latitude" in cols:
                batch.alter_column("latitude", existing_type=sa.Float(), nullable=True)
            if "longitude" in cols:
                batch.alter_column("longitude", existing_type=sa.Float(), nullable=True)

    if _has_table(inspector, "compliance_execution_ledger"):
        cols = _columns(inspector, "compliance_execution_ledger")
        if "payload" not in cols:
            with op.batch_alter_table("compliance_execution_ledger") as batch:
                batch.add_column(sa.Column("payload", sa.JSON(), nullable=True))

    if not _has_table(inspector, "compliance_export_metadata"):
        op.create_table(
            "compliance_export_metadata",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("export_type", sa.String(), nullable=False),
            sa.Column("workflow_type", sa.String(), nullable=False),
            sa.Column("storage_backend", sa.String(), nullable=False),
            sa.Column("storage_ref", sa.Text(), nullable=True),
            sa.Column("checksum", sa.String(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_compliance_export_metadata_tenant_id", "compliance_export_metadata", ["tenant_id"])
        op.create_index("ix_compliance_export_metadata_export_type", "compliance_export_metadata", ["export_type"])
        op.create_index("ix_compliance_export_metadata_workflow_type", "compliance_export_metadata", ["workflow_type"])
        op.create_index("ix_compliance_export_metadata_checksum", "compliance_export_metadata", ["checksum"])
        op.create_index("ix_compliance_export_metadata_created_at", "compliance_export_metadata", ["created_at"])
    else:
        cols = _columns(sa.inspect(bind), "compliance_export_metadata")
        with op.batch_alter_table("compliance_export_metadata") as batch:
            if "checksum" not in cols:
                batch.add_column(sa.Column("checksum", sa.String(), nullable=True))
            if "created_at" not in cols:
                batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        _create_index_if_missing(bind, "compliance_export_metadata", "ix_compliance_export_metadata_checksum", ["checksum"])
        _create_index_if_missing(bind, "compliance_export_metadata", "ix_compliance_export_metadata_created_at", ["created_at"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "compliance_export_metadata"):
        op.drop_table("compliance_export_metadata")
    # Other changes are intentionally additive/flexibility-preserving.

"""california compliance pack v0.1

Revision ID: 002_california_compliance_pack
Revises: 001
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "002_california_compliance_pack"
down_revision = "001"
branch_labels = None
depends_on = None

truth_label = sa.Enum("measured", "reported", "estimated", "calculated", "AI-inferred", name="compliance_truth_label")


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    if not _table_exists(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        truth_label.create(bind, checkfirst=True)
    truth_col = truth_label if bind.dialect.name != "sqlite" else sa.String(length=32)
    workflow_col = sa.String(length=96)

    _create_table_if_missing("compliance_jurisdictions", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("state", sa.String(), nullable=True), sa.Column("county", sa.String(), nullable=True), sa.Column("basin", sa.String()), sa.Column("subbasin", sa.String()), sa.Column("gsa", sa.String()), sa.Column("district", sa.String()), sa.Column("jurisdiction_pack", sa.String(), nullable=False), sa.Column("reporting_year", sa.String(), nullable=False), sa.Column("reporting_deadline", sa.Date(), nullable=False), sa.Column("workflow_type", workflow_col, nullable=False), sa.Column("created_at", sa.DateTime()))
    _create_table_if_missing("compliance_organization_roles", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("organization_name", sa.String(), nullable=False), sa.Column("owner", sa.String()), sa.Column("operator", sa.String()), sa.Column("reporting_agent", sa.String()), sa.Column("authorization_artifact_id", sa.String()), sa.Column("consent_scope", sa.Text()), sa.Column("reviewer_role", sa.String()))
    _create_table_if_missing("compliance_parcels", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("apn", sa.String(), nullable=False), sa.Column("geometry_ref", sa.Text()), sa.Column("geometry", sa.JSON()), sa.Column("county", sa.String()), sa.UniqueConstraint("tenant_id", "apn", name="uq_compliance_parcel_tenant_apn"))
    _create_table_if_missing("compliance_wells", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("parcel_id", sa.String(), sa.ForeignKey("compliance_parcels.id")), sa.Column("well_identifier", sa.String(), nullable=False), sa.Column("latitude", sa.Float(), nullable=False), sa.Column("longitude", sa.Float(), nullable=False), sa.Column("well_capacity", sa.Float()), sa.Column("capacity_unit", sa.String()), sa.UniqueConstraint("tenant_id", "well_identifier", name="uq_compliance_well_tenant_identifier"))
    _create_table_if_missing("compliance_meters", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("well_id", sa.String(), sa.ForeignKey("compliance_wells.id"), nullable=False), sa.Column("meter_identifier", sa.String(), nullable=False), sa.Column("manufacturer", sa.String()), sa.Column("serial_number", sa.String()), sa.Column("measurement_method", sa.String(), nullable=False), sa.Column("calibration_date", sa.Date()), sa.Column("calibration_document_ref", sa.Text()))
    _create_table_if_missing("compliance_measurements", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("measurement_type", sa.String(), nullable=False), sa.Column("source_system", sa.String(), nullable=False), sa.Column("truth_label", truth_col, nullable=False), sa.Column("source_timestamp", sa.DateTime(), nullable=False), sa.Column("ingestion_timestamp", sa.DateTime(), nullable=False), sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(), nullable=False), sa.Column("method", sa.String(), nullable=False), sa.Column("confidence", sa.Float()), sa.Column("quality_status", sa.String(), nullable=False), sa.Column("related_asset_type", sa.String(), nullable=False), sa.Column("related_asset_id", sa.String(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False), sa.Column("correction_lineage", sa.JSON()))
    _create_table_if_missing("compliance_execution_ledger", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("recommendation_id", sa.String()), sa.Column("approved_recommendation_id", sa.String()), sa.Column("scheduled_event_id", sa.String()), sa.Column("controller_command_id", sa.String()), sa.Column("applied_event_id", sa.String()), sa.Column("measured_extraction_id", sa.String()), sa.Column("variance", sa.Float()), sa.Column("operator_note", sa.Text()), sa.Column("truth_labels", sa.JSON(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False))
    _create_table_if_missing("compliance_water_budgets", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("allocation", sa.Float(), nullable=False), sa.Column("extraction", sa.Float(), nullable=False), sa.Column("irrigation_application", sa.Float(), nullable=False), sa.Column("remaining_balance", sa.Float(), nullable=False), sa.Column("projected_balance", sa.Float(), nullable=False), sa.Column("threshold_status", sa.String(), nullable=False), sa.Column("water_source", sa.String(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False))
    _create_table_if_missing("compliance_evidence", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("artifact_type", sa.String(), nullable=False), sa.Column("file_ref", sa.Text(), nullable=False), sa.Column("truth_label", truth_col, nullable=False), sa.Column("review_status", sa.String(), nullable=False), sa.Column("metadata_json", sa.JSON()), sa.Column("created_at", sa.DateTime()))
    _create_table_if_missing("compliance_rule_packs", sa.Column("id", sa.String(), primary_key=True), sa.Column("pack_id", sa.String(), nullable=False), sa.Column("version", sa.String(), nullable=False), sa.Column("effective_date", sa.Date(), nullable=False), sa.Column("workflow_type", workflow_col, nullable=False), sa.Column("required_fields", sa.JSON(), nullable=False), sa.Column("conditional_fields", sa.JSON(), nullable=False), sa.Column("validation_rules", sa.JSON(), nullable=False), sa.Column("deadlines", sa.JSON(), nullable=False), sa.Column("warning_thresholds", sa.JSON(), nullable=False), sa.Column("export_schema", sa.JSON(), nullable=False), sa.Column("disclaimer_text", sa.Text(), nullable=False))
    _create_table_if_missing("compliance_readiness_snapshots", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("workflow_type", workflow_col, nullable=False), sa.Column("reporting_year", sa.String(), nullable=False), sa.Column("readiness_status", sa.String(), nullable=False), sa.Column("readiness_percentage", sa.Float(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime()))

    for table, columns in {
        "compliance_jurisdictions": ["tenant_id", "county", "basin", "subbasin", "gsa", "reporting_year", "workflow_type"],
        "compliance_parcels": ["tenant_id", "apn"],
        "compliance_wells": ["tenant_id", "parcel_id", "well_identifier"],
        "compliance_meters": ["tenant_id", "well_id", "meter_identifier", "calibration_date"],
        "compliance_measurements": ["tenant_id", "related_asset_id", "reporting_period", "source_timestamp", "truth_label"],
        "compliance_water_budgets": ["tenant_id", "reporting_period", "water_source", "threshold_status"],
        "compliance_readiness_snapshots": ["tenant_id", "reporting_year", "workflow_type", "readiness_status"],
    }.items():
        for column in columns:
            _create_index_if_missing(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ["compliance_readiness_snapshots", "compliance_rule_packs", "compliance_evidence", "compliance_water_budgets", "compliance_execution_ledger", "compliance_measurements", "compliance_meters", "compliance_wells", "compliance_parcels", "compliance_organization_roles", "compliance_jurisdictions"]:
        if _table_exists(table):
            op.drop_table(table)
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        truth_label.drop(bind, checkfirst=True)

"""PostgreSQL smoke test for a verified pre-created compliance 002 schema."""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
from app.models.block import Block
from app.models.tenant import Tenant

TENANT_ID = "ci-precreated-tenant"


def _require_ci_database(database_url: str) -> None:
    db_name = make_url(database_url).database or ""
    if os.environ.get("ALLOW_COMPLIANCE_SMOKE_RESET") != "1" or "precreated" not in db_name:
        raise RuntimeError("Refusing to reset a database not marked for this CI smoke test")
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name):
        raise RuntimeError("Smoke database name must be a simple PostgreSQL identifier")


def _ensure_database(database_url: str) -> None:
    url = make_url(database_url)
    admin = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(sa.text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": url.database}).scalar()
        if not exists:
            connection.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def _reset(engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))


def _enum_types():
    truth = postgresql.ENUM("measured", "reported", "estimated", "calculated", "AI-inferred", name="compliance_truth_label")
    workflow = postgresql.ENUM("sgma_gsa_annual_report_readiness", "gears_groundwater_extractor_readiness", name="compliance_workflow_type")
    return truth, workflow


def _table(name: str, metadata: sa.MetaData, *columns, **kwargs):
    return sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True), *columns, **kwargs)


def _create_historical_002(engine) -> None:
    Base.metadata.create_all(bind=engine, tables=[Tenant.__table__, Block.__table__])
    metadata = sa.MetaData()
    truth, workflow = _enum_types()
    tenant_fk = lambda: sa.ForeignKey("tenants.id")
    _table("compliance_jurisdictions", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("state", sa.String(), nullable=False), sa.Column("county", sa.String(), nullable=False), sa.Column("basin", sa.String()), sa.Column("subbasin", sa.String()), sa.Column("gsa", sa.String()), sa.Column("district", sa.String()), sa.Column("jurisdiction_pack", sa.String(), nullable=False), sa.Column("reporting_year", sa.String(), nullable=False), sa.Column("reporting_deadline", sa.Date(), nullable=False), sa.Column("workflow_type", workflow, nullable=False), sa.Column("created_at", sa.DateTime()))
    _table("compliance_organization_roles", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("organization_name", sa.String(), nullable=False), sa.Column("owner", sa.String()), sa.Column("operator", sa.String()), sa.Column("reporting_agent", sa.String()), sa.Column("authorization_artifact_id", sa.String()), sa.Column("consent_scope", sa.Text()), sa.Column("reviewer_role", sa.String()))
    _table("compliance_parcels", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("apn", sa.String(), nullable=False), sa.Column("geometry_ref", sa.Text()), sa.Column("geometry", sa.JSON()), sa.Column("county", sa.String()), sa.UniqueConstraint("tenant_id", "apn", name="uq_compliance_parcel_tenant_apn"))
    _table("compliance_wells", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("parcel_id", sa.String(), sa.ForeignKey("compliance_parcels.id")), sa.Column("well_identifier", sa.String(), nullable=False), sa.Column("latitude", sa.Float(), nullable=False), sa.Column("longitude", sa.Float(), nullable=False), sa.Column("well_capacity", sa.Float()), sa.Column("capacity_unit", sa.String()), sa.UniqueConstraint("tenant_id", "well_identifier", name="uq_compliance_well_tenant_identifier"))
    _table("compliance_meters", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("well_id", sa.String(), sa.ForeignKey("compliance_wells.id"), nullable=False), sa.Column("meter_identifier", sa.String(), nullable=False), sa.Column("manufacturer", sa.String()), sa.Column("serial_number", sa.String()), sa.Column("measurement_method", sa.String(), nullable=False), sa.Column("calibration_date", sa.Date()), sa.Column("calibration_document_ref", sa.Text()))
    _table("compliance_measurements", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("measurement_type", sa.String(), nullable=False), sa.Column("source_system", sa.String(), nullable=False), sa.Column("truth_label", truth, nullable=False), sa.Column("source_timestamp", sa.DateTime(), nullable=False), sa.Column("ingestion_timestamp", sa.DateTime(), nullable=False), sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(), nullable=False), sa.Column("method", sa.String(), nullable=False), sa.Column("confidence", sa.Float()), sa.Column("quality_status", sa.String(), nullable=False), sa.Column("related_asset_type", sa.String(), nullable=False), sa.Column("related_asset_id", sa.String(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False), sa.Column("correction_lineage", sa.JSON()))
    _table("compliance_execution_ledger", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("recommendation_id", sa.String()), sa.Column("approved_recommendation_id", sa.String()), sa.Column("scheduled_event_id", sa.String()), sa.Column("controller_command_id", sa.String()), sa.Column("applied_event_id", sa.String()), sa.Column("measured_extraction_id", sa.String()), sa.Column("variance", sa.Float()), sa.Column("operator_note", sa.Text()), sa.Column("truth_labels", sa.JSON(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False))
    _table("compliance_water_budgets", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("allocation", sa.Float(), nullable=False), sa.Column("extraction", sa.Float(), nullable=False), sa.Column("irrigation_application", sa.Float(), nullable=False), sa.Column("remaining_balance", sa.Float(), nullable=False), sa.Column("projected_balance", sa.Float(), nullable=False), sa.Column("threshold_status", sa.String(), nullable=False), sa.Column("water_source", sa.String(), nullable=False), sa.Column("reporting_period", sa.String(), nullable=False))
    _table("compliance_evidence", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("artifact_type", sa.String(), nullable=False), sa.Column("file_ref", sa.Text(), nullable=False), sa.Column("truth_label", truth, nullable=False), sa.Column("review_status", sa.String(), nullable=False), sa.Column("metadata_json", sa.JSON()), sa.Column("created_at", sa.DateTime()))
    _table("compliance_rule_packs", metadata, sa.Column("pack_id", sa.String(), nullable=False), sa.Column("version", sa.String(), nullable=False), sa.Column("effective_date", sa.Date(), nullable=False), sa.Column("workflow_type", workflow, nullable=False), sa.Column("required_fields", sa.JSON(), nullable=False), sa.Column("conditional_fields", sa.JSON(), nullable=False), sa.Column("validation_rules", sa.JSON(), nullable=False), sa.Column("deadlines", sa.JSON(), nullable=False), sa.Column("warning_thresholds", sa.JSON(), nullable=False), sa.Column("export_schema", sa.JSON(), nullable=False), sa.Column("disclaimer_text", sa.Text(), nullable=False))
    _table("compliance_readiness_snapshots", metadata, sa.Column("tenant_id", sa.String(), tenant_fk(), nullable=False), sa.Column("workflow_type", workflow, nullable=False), sa.Column("reporting_year", sa.String(), nullable=False), sa.Column("readiness_status", sa.String(), nullable=False), sa.Column("readiness_percentage", sa.Float(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime()))
    metadata.create_all(engine)


def _seed_rows(engine) -> None:
    now = datetime.utcnow()
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO tenants (id,name,tier,active,created_at,updated_at) VALUES (:id,'Precreated CI Tenant','enterprise',true,:now,:now)"), {"id": TENANT_ID, "now": now})
        connection.execute(sa.text("INSERT INTO blocks (id,tenant_id,name,area_ha,water_budget_used,created_at,updated_at) VALUES ('block-1',:tenant_id,'Legacy Block',10,0,:now,:now)"), {"tenant_id": TENANT_ID, "now": now})
        connection.execute(sa.text("INSERT INTO compliance_parcels (id,tenant_id,apn,county) VALUES ('parcel-1',:tenant_id,'APN-1','Sonoma')"), {"tenant_id": TENANT_ID})
        connection.execute(sa.text("INSERT INTO compliance_wells (id,tenant_id,parcel_id,well_identifier,latitude,longitude,capacity_unit) VALUES ('well-1',:tenant_id,'parcel-1','WELL-1',38.1,-122.2,'gpm')"), {"tenant_id": TENANT_ID})
        connection.execute(sa.text("INSERT INTO compliance_jurisdictions (id,tenant_id,state,county,jurisdiction_pack,reporting_year,reporting_deadline,workflow_type,created_at) VALUES ('jur-1',:tenant_id,'CA','Sonoma','california_sgma_v0_1','2026',:deadline,'gears_groundwater_extractor_readiness',:now)"), {"tenant_id": TENANT_ID, "deadline": date(2026, 12, 31), "now": now})
        connection.execute(sa.text("INSERT INTO compliance_rule_packs (id,pack_id,version,effective_date,workflow_type,required_fields,conditional_fields,validation_rules,deadlines,warning_thresholds,export_schema,disclaimer_text) VALUES ('pack-1','california_sgma_v0_1','0.1',:effective_date,'gears_groundwater_extractor_readiness','{}','{}','{}','{}','{}','{}','Not legal advice')"), {"effective_date": date(2026, 1, 1)})


def _cfg(database_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _assert_shape(engine) -> None:
    inspector = sa.inspect(engine)
    assert "compliance_export_metadata" in inspector.get_table_names()
    parcel_cols = {c["name"]: c for c in inspector.get_columns("compliance_parcels")}
    well_cols = {c["name"]: c for c in inspector.get_columns("compliance_wells")}
    rule_cols = {c["name"]: c for c in inspector.get_columns("compliance_rule_packs")}
    assert parcel_cols["apn"]["nullable"] is True
    assert well_cols["latitude"]["nullable"] is True and well_cols["longitude"]["nullable"] is True
    assert "CHAR" in str(rule_cols["workflow_type"]["type"]).upper()
    with engine.begin() as connection:
        assert connection.execute(sa.text("SELECT parcel_identifier FROM compliance_parcels WHERE id='parcel-1'")).scalar_one() == "APN-1"
        connection.execute(sa.text("INSERT INTO compliance_parcels (id,tenant_id,apn,parcel_identifier) VALUES ('parcel-null-apn',:tenant_id,NULL,'GLOBAL-1')"), {"tenant_id": TENANT_ID})
        connection.execute(sa.text("INSERT INTO compliance_wells (id,tenant_id,parcel_id,well_identifier,latitude,longitude) VALUES ('well-null-coords',:tenant_id,'parcel-null-apn','WELL-NULL',NULL,NULL)"), {"tenant_id": TENANT_ID})
        connection.execute(sa.text("INSERT INTO compliance_rule_packs (id,pack_id,version,effective_date,workflow_type,required_fields,conditional_fields,validation_rules,deadlines,warning_thresholds,export_schema,disclaimer_text) VALUES ('pack-flex','custom','0.1',:effective_date,'custom_workflow_ci','{}','{}','{}','{}','{}','{}','Not legal advice')"), {"effective_date": date(2026, 1, 1)})
        assert connection.execute(sa.text("SELECT to_regtype('public.compliance_workflow_type')")).scalar_one() is None


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    _require_ci_database(database_url)
    _ensure_database(database_url)
    engine = sa.create_engine(database_url)
    try:
        _reset(engine)
        _create_historical_002(engine)
        _seed_rows(engine)
        cfg = _cfg(database_url)
        command.stamp(cfg, "002_california_compliance_pack")
        command.upgrade(cfg, "head")
        _assert_shape(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

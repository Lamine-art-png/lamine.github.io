import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Float, ForeignKey, JSON, MetaData, String, Table, create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app.compliance import services
from app.compliance.adapters import OpenETProvenanceAdapter, serialize_qanat_record
from app.compliance.constants import APPROVED_FIXTURE_TENANT_ID, RULE_PACKS
from app.compliance.repository import ComplianceRepository
from app.core.config import settings
from app.db import base as db_base
from app.models import Block, Tenant
from app.models.compliance import (
    ComplianceEvidence,
    ComplianceExecutionLedger,
    ComplianceMeasurement,
    ComplianceMeter,
    ComplianceOrganizationRole,
    ComplianceReadinessSnapshot,
    ComplianceWell,
)
from scripts.compliance_migration_preflight import collect_report

DEMO_HEADERS = {"X-Compliance-Demo-Token": "demo-token"}


def _enable_demo(monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-token")
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TENANT_ID", APPROVED_FIXTURE_TENANT_ID)


def _snapshot_count(session) -> int:
    return session.query(ComplianceReadinessSnapshot).filter_by(tenant_id=APPROVED_FIXTURE_TENANT_ID).count()


def _fresh_snapshot_count(session) -> int:
    fresh_session_factory = sessionmaker(bind=session.get_bind())
    fresh = fresh_session_factory()
    try:
        return _snapshot_count(fresh)
    finally:
        fresh.close()


def test_feature_flag_and_fail_closed_behavior(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", False)
    assert client.get("/v1/compliance/status").status_code == 404
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "")
    assert client.get("/v1/compliance/status", headers={"X-Organization-Id": "org-ca-vineyard-001"}).status_code == 403


def test_demo_token_is_pinned_to_approved_fixture_tenant(client, monkeypatch):
    _enable_demo(monkeypatch)
    response = client.get("/v1/compliance/status", headers={**DEMO_HEADERS, "X-Organization-Id": APPROVED_FIXTURE_TENANT_ID})
    assert response.status_code == 200
    payload = response.json()
    assert payload["organization"]["id"] == APPROVED_FIXTURE_TENANT_ID
    assert payload["demo_mode"] is True
    assert payload["rule_pack"]["status"] == "internal_alpha_pending_external_validation"
    mismatch = client.get("/v1/compliance/status", headers={**DEMO_HEADERS, "X-Organization-Id": "other-org"})
    assert mismatch.status_code == 403
    assert "does not match" in mismatch.json()["detail"]


def test_rule_pack_catalog_safety_defaults():
    assert settings.CALIFORNIA_COMPLIANCE_PACK_ENABLED is False
    assert settings.COMPLIANCE_DEMO_FIXTURES_ENABLED is False
    assert settings.COMPLIANCE_DEMO_TOKEN == ""
    assert settings.COMPLIANCE_ALLOW_BROWSER_TENANT_API_KEYS is False
    assert settings.COMPLIANCE_OBJECT_STORAGE_BACKEND == "disabled"
    assert RULE_PACKS["california_sgma_v0_1"]["status"] == "internal_alpha_pending_external_validation"
    assert RULE_PACKS["california_sgma_gsa_v0_1"]["status"] == "internal_alpha_pending_external_validation"
    assert RULE_PACKS["arizona_groundwater_alpha"]["status"] == "disabled_alpha"
    assert RULE_PACKS["global_research_template"]["status"] == "disabled_research_only"


def test_tenant_isolation_rejects_x_organization_id_mismatch(client, monkeypatch):
    _enable_demo(monkeypatch)
    response = client.get("/v1/compliance/assets/wells", headers={**DEMO_HEADERS, "X-Organization-Id": "other-org"})
    assert response.status_code == 403



def test_demo_fixture_seeding_provisions_only_approved_demo_tenant(db):
    assert db.query(Tenant).filter_by(id=APPROVED_FIXTURE_TENANT_ID).first() is None
    repo = ComplianceRepository(db, APPROVED_FIXTURE_TENANT_ID)
    repo.seed_demo_fixtures()
    tenant = db.query(Tenant).filter_by(id=APPROVED_FIXTURE_TENANT_ID).one()
    assert tenant.name == "Non-production representative California vineyard tenant"
    assert db.query(ComplianceWell).filter_by(tenant_id=APPROVED_FIXTURE_TENANT_ID).count() > 0
    assert db.query(ComplianceMeasurement).filter_by(tenant_id=APPROVED_FIXTURE_TENANT_ID).count() > 0


def test_production_repository_does_not_auto_create_tenant(db):
    repo = ComplianceRepository(db, "prod-tenant")
    assert repo.organization() == {"id": "prod-tenant"}
    assert db.query(Tenant).filter_by(id="prod-tenant").first() is None


def test_fixtures_cannot_be_seeded_for_another_tenant(db):
    with pytest.raises(ValueError):
        ComplianceRepository(db, "other-tenant").seed_demo_fixtures()

def test_truth_label_and_asset_tenant_enforcement(client, monkeypatch):
    _enable_demo(monkeypatch)
    payload = {"asset_type": "well", "asset_id": "well-sv-01", "measurement_type": "flow", "value": 1, "unit": "af", "method": "manual", "truth_label": "certified", "source_system": "manual", "source_timestamp": "2026-01-01T00:00:00Z", "reporting_period": "2026"}
    assert client.post("/v1/compliance/measurements", json=payload, headers=DEMO_HEADERS).status_code == 422
    payload["truth_label"] = "measured"
    assert client.post("/v1/compliance/measurements", json=payload, headers=DEMO_HEADERS).status_code == 201
    payload["asset_id"] = "not-this-tenant"
    assert client.post("/v1/compliance/measurements", json=payload, headers=DEMO_HEADERS).status_code == 422


def test_readiness_derives_gap_and_thresholds_from_records(client, monkeypatch):
    _enable_demo(monkeypatch)
    payload = client.get("/v1/compliance/readiness", headers=DEMO_HEADERS).json()
    assert payload["stale_telemetry"]
    gap = payload["stale_telemetry"][0]
    assert gap["asset_id"]
    assert gap["windows"]
    assert payload["missing_evidence"][0].startswith("manual_reading_evidence:")
    assert any(w["code"] == "stale_calibration" for w in payload["warnings"])
    assert any(w["code"] == "water_budget_threshold_alert" for w in payload["warnings"])


def test_workflow_pack_gates(client, monkeypatch):
    _enable_demo(monkeypatch)
    assert client.get("/v1/compliance/readiness", params={"workflow_type": "gears_groundwater_extractor_readiness"}, headers=DEMO_HEADERS).status_code == 200
    assert client.get("/v1/compliance/readiness", params={"workflow_type": "sgma_gsa_annual_report_readiness"}, headers=DEMO_HEADERS).status_code == 200
    assert services.resolve_workflow_pack("gears_groundwater_extractor_readiness")["status"] == "internal_alpha_pending_external_validation"
    assert services.resolve_workflow_pack("sgma_gsa_annual_report_readiness")["status"] == "internal_alpha_pending_external_validation"
    assert RULE_PACKS["arizona_groundwater_alpha"]["enabled"] is False
    assert client.get("/v1/compliance/readiness", params={"workflow_type": "research_readiness"}, headers=DEMO_HEADERS).status_code == 422
    assert client.post("/v1/compliance/exports", json={"export_type": "json", "workflow_type": "research_readiness"}, headers=DEMO_HEADERS).status_code == 422



class _RequiredFieldRepo:
    tenant_id = "required-field-tenant"

    def __init__(self, *, org=None, wells=None, meters=None, measurements=None, evidence=None, jurisdictions=None):
        self._org = org or {"id": self.tenant_id, "owner": "Owner"}
        self._wells = wells if wells is not None else [{"id": "well-1", "well_identifier": "W-1", "latitude": 1.0, "longitude": 2.0}]
        self._meters = meters if meters is not None else [{"id": "meter-1", "measurement_method": "flow_meter"}]
        self._measurements = measurements if measurements is not None else [
            {"id": f"m-{month}", "asset_type": "well", "asset_id": "well-1", "measurement_type": "groundwater_extraction", "reporting_period": "2026", "source_timestamp": f"2026-{month:02d}-01T00:00:00Z"}
            for month in range(1, 13)
        ]
        self._evidence = evidence if evidence is not None else []
        self._jurisdictions = jurisdictions if jurisdictions is not None else [{"workflow_type": "gears_groundwater_extractor_readiness", "reporting_year": "2026"}]

    def organization(self):
        return self._org

    def list_wells(self):
        return self._wells

    def list_meters(self):
        return self._meters

    def list_measurements(self):
        return self._measurements

    def list_evidence(self):
        return self._evidence

    def list_jurisdictions(self):
        return self._jurisdictions


def test_required_field_paths_are_detected():
    workflow = "gears_groundwater_extractor_readiness"
    cases = [
        (_RequiredFieldRepo(wells=[]), "well_identifier"),
        (_RequiredFieldRepo(wells=[{"id": "well-1", "well_identifier": "", "latitude": 1, "longitude": 2}]), "well_identifier"),
        (_RequiredFieldRepo(wells=[{"id": "well-1", "well_identifier": "W", "latitude": None, "longitude": 2}]), "well_location"),
        (_RequiredFieldRepo(meters=[]), "measurement_method"),
        (_RequiredFieldRepo(meters=[{"id": "meter-1", "measurement_method": ""}]), "measurement_method"),
        (_RequiredFieldRepo(measurements=[]), "monthly_groundwater_extraction_volumes"),
        (_RequiredFieldRepo(measurements=[{"id": "m-1", "asset_type": "well", "asset_id": "well-1", "measurement_type": "groundwater_extraction", "reporting_period": "2026", "source_timestamp": "2026-01-01T00:00:00Z"}]), "monthly_groundwater_extraction_coverage"),
        (_RequiredFieldRepo(wells=[{"id": "well-1", "well_identifier": "W-1", "latitude": 1, "longitude": 2}, {"id": "well-2", "well_identifier": "W-2", "latitude": 1, "longitude": 2}]), "monthly_groundwater_extraction_coverage"),
        (_RequiredFieldRepo(org={"id": "required-field-tenant", "owner": "Owner", "reporting_agent": "Agent"}, evidence=[]), "agent_authorization_evidence"),
    ]
    for repo, expected in cases:
        assert expected in services.validate_required_fields(repo, workflow)

def test_different_pack_thresholds_change_readiness(db, monkeypatch):
    repo = ComplianceRepository(db, APPROVED_FIXTURE_TENANT_ID)
    repo.seed_demo_fixtures()
    custom = dict(RULE_PACKS["california_sgma_v0_1"])
    custom["pack_id"] = "strict_pack"
    custom["workflow_type"] = "strict_readiness"
    custom["thresholds"] = {**custom["thresholds"], "water_budget_remaining_pct_alert": 90}
    monkeypatch.setitem(RULE_PACKS, "strict_pack", custom)
    base = services.readiness(repo, "gears_groundwater_extractor_readiness")
    strict = services.readiness(repo, "strict_readiness")
    assert strict["readiness_percentage"] <= base["readiness_percentage"]
    assert strict["rule_pack"]["pack_id"] == "strict_pack"


def test_export_package_persists_metadata_and_fails_closed_for_binary(client, monkeypatch):
    _enable_demo(monkeypatch)
    response = client.post("/v1/compliance/exports", json={"export_type": "json", "workflow_type": "gears_groundwater_extractor_readiness"}, headers=DEMO_HEADERS)
    assert response.status_code == 201
    package = response.json()
    assert package["provenance"]["direct_filing"] is False
    assert package["provenance"]["secure_download_available"] is False
    assert package["storage_status"] == "metadata_persisted_object_storage_disabled"
    assert package["storage_ref"] is None
    assert package["checksum"]
    assert "content" not in package
    assert client.get(f"/v1/compliance/exports/{package['id']}", headers=DEMO_HEADERS).status_code == 200
    assert client.post("/v1/compliance/exports", json={"export_type": "csv"}, headers=DEMO_HEADERS).status_code == 422
    assert client.post("/v1/compliance/exports", json={"export_type": "pdf"}, headers=DEMO_HEADERS).status_code == 422
    assert client.post("/v1/compliance/exports", json={"export_type": "xlsx"}, headers=DEMO_HEADERS).status_code == 422


def test_export_gap_flags_are_scoped_to_selected_reporting_year(client, db, monkeypatch):
    _enable_demo(monkeypatch)
    repo = ComplianceRepository(db, APPROVED_FIXTURE_TENANT_ID)
    repo.seed_demo_fixtures()
    repo.add_measurement({
        "asset_type": "well",
        "asset_id": "well-sv-01",
        "measurement_type": "groundwater_extraction",
        "value": 1,
        "unit": "acre_feet",
        "method": "flow_meter_totalizer",
        "truth_label": "estimated",
        "source_system": "AGRO-AI",
        "source_timestamp": "2025-06-28T23:59:00Z",
        "reporting_period": "2025",
        "quality_status": "gap_estimate",
        "correction_lineage": [{"missing_window": "2025-06-12/2025-06-20"}],
    })
    before = _snapshot_count(db)
    response = client.post("/v1/compliance/exports", json={"export_type": "json", "workflow_type": "gears_groundwater_extractor_readiness"}, headers=DEMO_HEADERS)
    assert response.status_code == 201
    package = response.json()
    assert package["reporting_year"] == "2026"
    assert _snapshot_count(db) == before + 1
    assert package["missing_data_flags"]
    assert all(flag.endswith(":2026") for flag in package["missing_data_flags"])
    assert all("2025" not in assumption for assumption in package["assumptions"])
    assert package["historical_measurements_excluded_count"] >= 1
    assert all(str(measurement["reporting_period"]) == "2026" for measurement in package["measurements"])
    assert all(measurement["source_timestamp"] != "2025-06-28T23:59:00" for measurement in package["measurements"])


def test_jurisdiction_serializes_global_fields(client, monkeypatch):
    _enable_demo(monkeypatch)
    response = client.get("/v1/compliance/jurisdictions", headers=DEMO_HEADERS)
    assert response.status_code == 200
    jurisdiction = response.json()[0]
    assert jurisdiction["country"] == "US"
    assert jurisdiction["jurisdiction_level"] == "state"
    assert jurisdiction["authority_name"]


def test_status_returns_api_backed_summary_without_snapshot(client, db, monkeypatch):
    _enable_demo(monkeypatch)
    before = _snapshot_count(db)
    response = client.get("/v1/compliance/status", headers=DEMO_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["water_budgets"]
    assert payload["reconciliation_summary"]
    assert payload["upcoming_deadlines"]
    assert isinstance(payload["missing_evidence_count"], int)
    assert isinstance(payload["unresolved_anomaly_count"], int)
    assert _snapshot_count(db) == before


def test_readiness_get_is_read_only(client, db, monkeypatch):
    _enable_demo(monkeypatch)
    before = _snapshot_count(db)
    response = client.get("/v1/compliance/readiness", headers=DEMO_HEADERS)
    assert response.status_code == 200
    assert response.json()["workflow_type"] == "gears_groundwater_extractor_readiness"
    assert _snapshot_count(db) == before


def test_readiness_snapshot_post_commits_once_and_survives_fresh_session(client, db, monkeypatch):
    _enable_demo(monkeypatch)
    before = _snapshot_count(db)
    response = client.post("/v1/compliance/readiness/snapshots", headers=DEMO_HEADERS)
    assert response.status_code == 201
    payload = response.json()
    assert payload["snapshot"]["tenant_id"] == APPROVED_FIXTURE_TENANT_ID
    assert payload["readiness"]["workflow_type"] == "gears_groundwater_extractor_readiness"
    assert _snapshot_count(db) == before + 1
    assert _fresh_snapshot_count(db) == before + 1


def test_reconciliation_variance_percentage_from_persisted_values(db):
    tenant = Tenant(id="ledger-tenant", name="Ledger Tenant")
    db.add(tenant)
    db.add(ComplianceExecutionLedger(
        id="ledger-1", tenant_id="ledger-tenant", recommendation_id="rec-1", measured_extraction_id="meas-1",
        variance=None, operator_note=None, truth_labels={"variance_pct": "calculated"}, reporting_period="2026",
        payload={"planned_volume_af": 10.0, "applied_volume_af": 12.5},
    ))
    db.commit()
    row = services.reconciliation(ComplianceRepository(db, "ledger-tenant"))[0]
    assert row["variance_af"] == 2.5
    assert row["variance_pct"] == 25.0

def test_qanat_mapping_serializer():
    mapped = serialize_qanat_record({"parcel_identifier": "GLOBAL-123", "apn": "123-456", "parcel_geometry_ref": "s3://parcel.geojson", "well_identifier": "W-1", "extraction_volume": 2.5, "reporting_period": 2026, "source_provenance": {"file": "qanat.csv"}})
    assert mapped["parcel"]["parcel_identifier"] == "GLOBAL-123"
    assert mapped["parcel"]["apn"] == "123-456"
    assert mapped["extraction_volume"]["truth_label"] == "reported"


def test_openet_estimated_value_labeling():
    measurement = OpenETProvenanceAdapter().to_measurement({"date_window": "2026-05-01/2026-05-31", "geometry_ref": "parcel-sv-101", "et_value": 87.2, "source_model": "ensemble"})
    assert measurement["truth_label"] == "estimated"
    assert measurement["measurement_type"] == "estimated_et"


def test_startup_init_does_not_create_compliance_tables(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(db_base, "engine", engine)
    db_base.init_db()
    tables = inspect(engine).get_table_names()
    assert "tenants" in tables
    assert not any(table.startswith("compliance_") for table in tables)



def _alembic_config(sqlite_path: Path) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{sqlite_path}")
    return cfg


def _bootstrap_legacy_baseline(sqlite_path: Path) -> None:
    engine = create_engine(f"sqlite:///{sqlite_path}")
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    db_base.Base.metadata.create_all(bind=engine, tables=[Tenant.__table__, Block.__table__])


def test_full_fresh_sqlite_alembic_upgrade_001_through_003(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    _bootstrap_legacy_baseline(db_path)
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    tables = inspect(engine).get_table_names()
    assert "compliance_export_metadata" in tables
    assert "compliance_parcels" in tables


def test_upgraded_sqlite_alembic_upgrade_002_through_003(tmp_path, monkeypatch):
    db_path = tmp_path / "upgraded.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    _bootstrap_legacy_baseline(db_path)
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "002_california_compliance_pack")
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    cols = {column["name"] for column in inspect(engine).get_columns("compliance_parcels")}
    assert "parcel_identifier" in cols
    assert "compliance_export_metadata" in inspect(engine).get_table_names()


def test_compliance_migration_preflight_classifies_clean_002_and_003(tmp_path, monkeypatch):
    db_path = tmp_path / "preflight.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    _bootstrap_legacy_baseline(db_path)
    assert collect_report(database_url)["schema_classification"] == "A_clean_baseline_no_compliance_tables"

    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "002_california_compliance_pack")
    report_002 = collect_report(database_url)
    assert report_002["current_alembic_revision"] == "002_california_compliance_pack"
    assert report_002["schema_classification"] == "B_migration_002_schema"
    assert report_002["tables"]["compliance_export_metadata"] is False
    assert report_002["parcel_identifier_exists"] is False

    command.upgrade(cfg, "head")
    report_head = collect_report(database_url)
    assert report_head["current_alembic_revision"] == "008_saas_portal_v2_1_security"
    assert report_head["schema_classification"] == "C_migration_003_schema"
    assert report_head["tables"]["compliance_export_metadata"] is True
    assert report_head["parcel_identifier_exists"] is True

def _load_migration_003():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "003_global_compliance_kernel.py"
    spec = importlib.util.spec_from_file_location("migration_003", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration_003(connection):
    module = _load_migration_003()
    context = MigrationContext.configure(connection)
    op = Operations(context)
    original = module.op
    module.op = op
    try:
        module.upgrade()
    finally:
        module.op = original


def _base_tenant_table(metadata):
    Table("tenants", metadata, Column("id", String, primary_key=True))


def _california_tables(metadata):
    _base_tenant_table(metadata)
    Table("compliance_jurisdictions", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False), Column("state", String, nullable=False), Column("county", String, nullable=False), Column("workflow_type", String(64), nullable=False))
    Table("compliance_rule_packs", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, nullable=True), Column("workflow_type", String(64), nullable=False))
    Table("compliance_readiness_snapshots", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False), Column("workflow_type", String(64), nullable=False))
    Table("compliance_parcels", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False), Column("apn", String, nullable=False), Column("geometry", JSON), Column("county", String))
    Table("compliance_wells", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False), Column("parcel_id", String), Column("well_identifier", String, nullable=False), Column("latitude", Float, nullable=False), Column("longitude", Float, nullable=False))
    Table("compliance_execution_ledger", metadata, Column("id", String, primary_key=True), Column("tenant_id", String, ForeignKey("tenants.id"), nullable=False), Column("truth_labels", JSON, nullable=False), Column("reporting_period", String, nullable=False))


def test_migration_003_smoke_fresh_sqlite_database():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    metadata = MetaData()
    _base_tenant_table(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        _run_migration_003(connection)
        assert "compliance_export_metadata" in inspect(connection).get_table_names()


def test_migration_003_smoke_upgraded_california_sqlite_database():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _record: conn.execute("PRAGMA foreign_keys=ON"))
    metadata = MetaData()
    _california_tables(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Table("tenants", metadata, autoload_with=connection).insert(), {"id": "tenant-1"})
        connection.execute(Table("compliance_parcels", metadata, autoload_with=connection).insert(), {"id": "parcel-1", "tenant_id": "tenant-1", "apn": "APN-1", "county": "Sonoma"})
        _run_migration_003(connection)
        cols = {column["name"]: column for column in inspect(connection).get_columns("compliance_parcels")}
        assert "parcel_identifier" in cols
        assert cols["apn"]["nullable"] is True
        row = connection.execute(Table("compliance_parcels", MetaData(), autoload_with=connection).select()).mappings().one()
        assert row["parcel_identifier"] == "APN-1"
        well_cols = {column["name"]: column for column in inspect(connection).get_columns("compliance_wells")}
        assert well_cols["latitude"]["nullable"] is True

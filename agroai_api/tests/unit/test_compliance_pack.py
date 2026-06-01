import pytest

from app.api.v1.compliance import get_compliance_repo
from app.compliance.adapters import OpenETProvenanceAdapter, serialize_qanat_record
from app.compliance.repository import ComplianceContext, ComplianceRepository
from app.compliance import services
from app.core.config import settings
from app.models import Tenant
from app.services.api_key_service import APIKeyService


def _repo(db):
    repo = ComplianceRepository(db, ComplianceContext("org-ca-vineyard-001", demo_mode=True))
    repo.seed_demo_fixture_if_empty()
    return repo


def _api_key(db, tenant_id="tenant-auth-1"):
    db.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}", tier="enterprise", active=True))
    db.commit()
    _, full_key = APIKeyService.create_api_key(db, tenant_id=tenant_id, name="test compliance key")
    return full_key


def test_feature_flag_behavior(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", False)
    assert client.get("/v1/compliance/status").status_code == 404
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-test-token")
    response = client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": "demo-test-token"})
    assert response.status_code == 200
    assert response.json()["feature_flag"] == "CALIFORNIA_COMPLIANCE_PACK_ENABLED"


def test_requires_auth_without_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    assert client.get("/v1/compliance/status").status_code == 401


def test_demo_mode_requires_explicit_non_production_token(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-test-token")
    assert client.get("/v1/compliance/status").status_code == 401
    assert client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": "wrong"}).status_code == 401
    assert client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": "demo-test-token"}).status_code == 200


def test_authenticated_tenant_access_and_header_match(db, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    full_key = _api_key(db, "tenant-auth-1")
    repo = get_compliance_repo(db=db, x_api_key=full_key, x_organization_id="tenant-auth-1")
    assert repo.tenant_id == "tenant-auth-1"


def test_mismatched_organization_header_rejected(db, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    full_key = _api_key(db, "tenant-auth-1")
    with pytest.raises(Exception) as exc:
        get_compliance_repo(db=db, x_api_key=full_key, x_organization_id="tenant-auth-2")
    assert getattr(exc.value, "status_code", None) == 403


def test_cross_tenant_repository_isolation(db):
    repo_a = _repo(db)
    repo_b = ComplianceRepository(db, ComplianceContext("tenant-b", demo_mode=False))
    assert repo_a.wells()
    assert repo_b.wells() == []


def test_fixture_data_absent_when_demo_flag_false(db, monkeypatch):
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    repo = ComplianceRepository(db, ComplianceContext("org-ca-vineyard-001", demo_mode=False))
    assert repo.wells() == []
    assert repo.jurisdictions() == []


def test_truth_label_enforcement(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-test-token")
    headers = {"X-Compliance-Demo-Token": "demo-test-token"}
    payload = {"asset_type": "well", "asset_id": "well-sv-01", "measurement_type": "flow", "value": 1, "unit": "af", "method": "manual", "truth_label": "certified", "source_system": "manual", "source_timestamp": "2026-01-01T00:00:00Z", "reporting_period": "2026"}
    assert client.post("/v1/compliance/measurements", json=payload, headers=headers).status_code == 422
    payload["truth_label"] = "measured"
    assert client.post("/v1/compliance/measurements", json=payload, headers=headers).status_code == 201


def test_required_field_validation_and_agent_authorization(db):
    repo = _repo(db)
    result = services.readiness_from_repository(repo, "gears_groundwater_extractor_readiness")
    assert "agent_authorization_evidence" not in result["missing_required_fields"]
    empty = ComplianceRepository(db, ComplianceContext("unknown-org", demo_mode=False))
    assert "owner_details" in services.readiness_from_repository(empty)["missing_required_fields"]


def test_missing_telemetry_stale_calibration_and_budget_alert(db):
    result = services.readiness_from_repository(_repo(db))
    assert result["stale_telemetry"]
    assert any(w["code"] == "stale_calibration" for w in result["warnings"])
    assert any(w["code"] == "water_budget_threshold_alert" for w in result["warnings"])


def test_water_budget_calculations(db):
    budget = services.water_budget_status_from_records(_repo(db).water_budgets())[0]
    assert budget["remaining_balance_af"] == 10.9
    assert budget["threshold_status"] == "alert"
    assert budget["truth_labels"]["remaining_balance_af"] == "calculated"


def test_recommendation_to_application_variance(db):
    row = _repo(db).reconciliation()[0]
    assert row["variance_pct"] > 10
    assert row["truth_labels"]["recommended_volume_af"] == "AI-inferred"
    assert row["truth_labels"]["variance_af"] == "calculated"


def test_export_package_generation(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-test-token")
    monkeypatch.setattr(settings, "COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK", True)
    headers = {"X-Compliance-Demo-Token": "demo-test-token"}
    for export_type in ("json", "csv", "xlsx", "pdf"):
        response = client.post("/v1/compliance/exports", json={"export_type": export_type, "workflow_type": "gears_groundwater_extractor_readiness"}, headers=headers)
        assert response.status_code == 201
        package = response.json()
        assert package["provenance"]["direct_filing"] is False
        assert package["checksum_sha256"]
        assert package["storage_ref"].startswith("db://")
        assert "content_base64" not in package
        fetched = client.get(f"/v1/compliance/exports/{package['id']}", headers=headers)
        assert fetched.status_code == 200


def test_qanat_mapping_serializer():
    mapped = serialize_qanat_record({"parcel_identifier": "123-456", "parcel_geometry_ref": "s3://parcel.geojson", "well_identifier": "W-1", "extraction_volume": 2.5, "reporting_period": 2026, "source_provenance": {"file": "qanat.csv"}})
    assert mapped["parcel"]["apn"] == "123-456"
    assert mapped["extraction_volume"]["truth_label"] == "reported"
    assert mapped["source_provenance"]["file"] == "qanat.csv"


def test_openet_estimated_value_labeling():
    measurement = OpenETProvenanceAdapter().to_measurement({"date_window": "2026-05-01/2026-05-31", "geometry_ref": "parcel-sv-101", "et_value": 87.2, "source_model": "ensemble"})
    assert measurement["truth_label"] == "estimated"
    assert measurement["measurement_type"] == "estimated_et"


def test_demo_token_cannot_select_other_tenant_exports(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "demo-test-token")
    monkeypatch.setattr(settings, "COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK", True)
    response = client.post("/v1/compliance/exports", json={"export_type": "json", "workflow_type": "gears_groundwater_extractor_readiness"}, headers={"X-Compliance-Demo-Token": "demo-test-token", "X-Organization-Id": "tenant-b"})
    assert response.status_code == 403


def test_rule_pack_gating(db):
    repo = _repo(db)
    assert services.readiness_from_repository(repo, "gears_groundwater_extractor_readiness")["disclaimer"]
    with pytest.raises(ValueError):
        services.readiness_from_repository(repo, "unknown_workflow")
    with pytest.raises(PermissionError):
        services.readiness_from_repository(repo, "az_groundwater_withdrawal_readiness")
    with pytest.raises(PermissionError):
        services.readiness_from_repository(repo, "us_co_water_rights_research_readiness")


def test_measurement_rejects_missing_cross_tenant_asset_and_bad_timestamp(db):
    repo = _repo(db)
    valid = {"asset_type": "well", "asset_id": "well-sv-01", "measurement_type": "flow", "value": 1, "unit": "af", "method": "manual", "truth_label": "measured", "source_system": "manual", "source_timestamp": "2026-01-01T00:00:00Z", "reporting_period": "2026"}
    bad_asset = {**valid, "asset_id": "other-tenant-well"}
    with pytest.raises(ValueError, match="related asset"):
        repo.add_measurement(bad_asset)
    bad_ts = {**valid, "source_timestamp": "not-a-timestamp"}
    with pytest.raises(ValueError, match="source_timestamp"):
        repo.add_measurement(bad_ts)


def test_dynamic_readiness_no_fixture_leakage(db):
    repo = ComplianceRepository(db, ComplianceContext("tenant-dynamic", demo_mode=False))
    assert services.readiness_from_repository(repo, "gears_groundwater_extractor_readiness")["next_required_action"] != "Attach manual reading evidence for June telemetry gap before export review."


def test_database_export_fallback_fails_closed_by_default(db, monkeypatch):
    monkeypatch.setattr(settings, "COMPLIANCE_EXPORT_STORAGE_BACKEND", "database_dev_fallback")
    monkeypatch.setattr(settings, "COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK", False)
    with pytest.raises(RuntimeError, match="COMPLIANCE_ALLOW_DATABASE_DEV_FALLBACK"):
        services.compose_export_from_repository(_repo(db), "json", "gears_groundwater_extractor_readiness")


def test_demo_mode_fails_closed_when_token_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_TOKEN", "")
    response = client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": "anything"})
    assert response.status_code == 500


def test_dynamic_gap_uses_tenant_asset_ids_not_fixture_values(db):
    from datetime import date, datetime
    from app.models.compliance import ComplianceEvidence, ComplianceMeasurement, ComplianceMeter, ComplianceOrganizationRole, ComplianceParcel, ComplianceWell

    db.add(Tenant(id="tenant-dynamic-gap", name="Dynamic Gap Tenant", tier="enterprise", active=True))
    db.add(ComplianceOrganizationRole(id="role-dynamic-gap", tenant_id="tenant-dynamic-gap", organization_name="Dynamic Gap Tenant", owner="Owner", reporting_agent="Agent"))
    db.add(ComplianceEvidence(id="ev-dynamic-agent", tenant_id="tenant-dynamic-gap", artifact_type="agent_authorization", file_ref="s3://dynamic/auth.pdf", truth_label="reported", review_status="accepted"))
    db.add(ComplianceParcel(id="parcel-dynamic", tenant_id="tenant-dynamic-gap", apn="DYN-1"))
    db.add(ComplianceWell(id="well-dynamic-77", tenant_id="tenant-dynamic-gap", parcel_id="parcel-dynamic", well_identifier="DYN-WELL-77", latitude=33.1, longitude=-111.1))
    db.add(ComplianceMeter(id="meter-dynamic", tenant_id="tenant-dynamic-gap", well_id="well-dynamic-77", meter_identifier="DYN-MTR", measurement_method="manual", calibration_date=date(2020, 1, 1)))
    db.add(ComplianceMeasurement(id="meas-dynamic-gap", tenant_id="tenant-dynamic-gap", measurement_type="groundwater_extraction", source_system="manual", truth_label="estimated", source_timestamp=datetime(2026, 3, 1), ingestion_timestamp=datetime(2026, 3, 2), value=1.5, unit="acre_feet", method="interpolation", quality_status="gap_estimate", related_asset_type="well", related_asset_id="well-dynamic-77", reporting_period="2026", correction_lineage=[{"reason": "sensor gap", "missing_window": "2026-02-10/2026-02-12"}]))
    db.commit()
    result = services.readiness_from_repository(ComplianceRepository(db, ComplianceContext("tenant-dynamic-gap")), "gears_groundwater_extractor_readiness")
    assert result["stale_telemetry"][0]["asset_id"] == "well-dynamic-77"
    assert result["stale_telemetry"][0]["window"] == "2026-02-10/2026-02-12"
    assert "SV-WELL" not in result["next_required_action"]

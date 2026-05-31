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
    response = client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": settings.COMPLIANCE_DEMO_TOKEN})
    assert response.status_code == 200
    assert response.json()["feature_flag"] == "CALIFORNIA_COMPLIANCE_PACK_ENABLED"


def test_requires_auth_without_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", False)
    assert client.get("/v1/compliance/status").status_code == 401


def test_demo_mode_requires_explicit_non_production_token(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    monkeypatch.setattr(settings, "COMPLIANCE_DEMO_FIXTURES_ENABLED", True)
    assert client.get("/v1/compliance/status").status_code == 401
    assert client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": "wrong"}).status_code == 401
    assert client.get("/v1/compliance/status", headers={"X-Compliance-Demo-Token": settings.COMPLIANCE_DEMO_TOKEN}).status_code == 200


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
    headers = {"X-Compliance-Demo-Token": settings.COMPLIANCE_DEMO_TOKEN}
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
    headers = {"X-Compliance-Demo-Token": settings.COMPLIANCE_DEMO_TOKEN}
    for export_type in ("json", "csv", "xlsx", "pdf"):
        response = client.post("/v1/compliance/exports", json={"export_type": export_type, "workflow_type": "gears_groundwater_extractor_readiness"}, headers=headers)
        assert response.status_code == 201
        package = response.json()
        assert package["provenance"]["direct_filing"] is False
        assert package["checksum_sha256"]
        assert package["storage_ref"].startswith("db://")
        assert package["content_base64"]
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

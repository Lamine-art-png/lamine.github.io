from app.compliance.adapters import OpenETProvenanceAdapter, serialize_qanat_record
from app.compliance import services
from app.core.config import settings


def test_feature_flag_behavior(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", False)
    assert client.get("/v1/compliance/status").status_code == 404
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    response = client.get("/v1/compliance/status")
    assert response.status_code == 200
    assert response.json()["feature_flag"] == "CALIFORNIA_COMPLIANCE_PACK_ENABLED"


def test_tenant_isolation(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    assert client.get("/v1/compliance/assets/wells").json()
    assert client.get("/v1/compliance/assets/wells", headers={"X-Organization-Id": "other-org"}).json() == []


def test_truth_label_enforcement(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    payload = {"asset_type": "well", "asset_id": "well-sv-01", "measurement_type": "flow", "value": 1, "unit": "af", "method": "manual", "truth_label": "certified", "source_system": "manual", "source_timestamp": "2026-01-01T00:00:00Z", "reporting_period": "2026"}
    assert client.post("/v1/compliance/measurements", json=payload).status_code == 422
    payload["truth_label"] = "measured"
    assert client.post("/v1/compliance/measurements", json=payload).status_code == 201


def test_required_field_validation_and_agent_authorization():
    assert "agent_authorization_evidence" not in services.validate_required_fields("gears_groundwater_extractor_readiness")
    assert "owner_details" in services.validate_required_fields("gears_groundwater_extractor_readiness", "unknown-org")


def test_missing_telemetry_stale_calibration_and_budget_alert():
    result = services.readiness()
    assert result["stale_telemetry"]
    assert any(w["code"] == "stale_calibration" for w in result["warnings"])
    assert any(w["code"] == "water_budget_threshold_alert" for w in result["warnings"])


def test_water_budget_calculations():
    budget = services.water_budget_status()[0]
    assert budget["remaining_balance_af"] == 10.9
    assert budget["threshold_status"] == "alert"
    assert budget["truth_labels"]["remaining_balance_af"] == "calculated"


def test_recommendation_to_application_variance():
    row = services.reconciliation()[0]
    assert row["variance_pct"] > 10
    assert row["truth_labels"]["recommended_volume_af"] == "AI-inferred"
    assert row["truth_labels"]["variance_af"] == "calculated"


def test_export_package_generation(client, monkeypatch):
    monkeypatch.setattr(settings, "CALIFORNIA_COMPLIANCE_PACK_ENABLED", True)
    response = client.post("/v1/compliance/exports", json={"export_type": "json", "workflow_type": "gears_groundwater_extractor_readiness"})
    assert response.status_code == 201
    package = response.json()
    assert package["direct_filing"] is False if "direct_filing" in package else package["provenance"]["direct_filing"] is False
    assert "truth_labels_required" in package["provenance"]
    fetched = client.get(f"/v1/compliance/exports/{package['id']}")
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

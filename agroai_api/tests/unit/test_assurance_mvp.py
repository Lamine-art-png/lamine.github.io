import base64
from datetime import datetime
from io import BytesIO

import pytest

from app.assurance.models import AssuranceEvidenceArtifact, AssuranceExport, AssurancePassport, RulePack
from app.agents.models import AgentWorkflowRun
from app.models import Tenant
from app.models.compliance import ComplianceMeasurement, ComplianceMeter, ComplianceParcel, ComplianceWaterBudget, ComplianceWell
from app.services.api_key_service import APIKeyService
from app.services import workbench_engine


def _headers_for(db, tenant_id="assurance-tenant"):
    if not db.query(Tenant).filter_by(id=tenant_id).first():
        db.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}", email=f"{tenant_id}@example.com", tier="enterprise", active=True))
        db.commit()
    _, key = APIKeyService.create_api_key(db, tenant_id=tenant_id, name="assurance-test", role="analyst")
    return {"X-API-Key": key, "X-Organization-Id": tenant_id}


def _create_passport(client, headers, **overrides):
    payload = {
        "farm_name": "North Valley Ranch",
        "farm_location": "Central Valley",
        "crop": "tomatoes",
        "season": "2026",
        "reporting_period": "2026",
    }
    payload.update(overrides)
    response = client.post("/v1/assurance/passports", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["passport"]["id"]


def test_assurance_tenant_isolation(client, db):
    headers_a = _headers_for(db, "tenant-a")
    headers_b = _headers_for(db, "tenant-b")
    passport_id = _create_passport(client, headers_a)

    assert client.get(f"/v1/assurance/passports/{passport_id}", headers=headers_a).status_code == 200
    assert client.get(f"/v1/assurance/passports/{passport_id}", headers=headers_b).status_code == 404
    mismatch = client.get(f"/v1/assurance/passports/{passport_id}", headers={**headers_a, "X-Organization-Id": "tenant-b"})
    assert mismatch.status_code == 403


def test_passport_creation_seeds_sections_checklist_and_rule_packs(client, db):
    headers = _headers_for(db)
    passport_id = _create_passport(client, headers)

    assert db.query(AssurancePassport).filter_by(id=passport_id, tenant_id="assurance-tenant").count() == 1
    assert db.query(RulePack).filter_by(id="waterops_generic_v0_1").count() == 1
    body = client.get(f"/v1/assurance/passports/{passport_id}", headers=headers).json()
    assert len(body["sections"]) >= 6
    assert body["passport"]["status"] in {"draft", "missing_proof"}
    assert body["disclaimer"]


def test_evidence_upload_metadata_is_tenant_scoped(client, db):
    headers = _headers_for(db)
    passport_id = _create_passport(client, headers)
    response = client.post(
        f"/v1/assurance/passports/{passport_id}/evidence",
        headers=headers,
        json={
            "evidence_type": "water_measurement",
            "proof_domain": "water_proof",
            "file_ref": "s3://not-configured/example.csv",
            "filename": "meter.csv",
            "content_type": "text/csv",
            "checksum": "abc123",
            "truth_label": "measured",
            "metadata": {"rows_detected": 12},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "meter.csv"
    assert body["metadata"]["rows_detected"] == 12
    assert db.query(AssuranceEvidenceArtifact).filter_by(tenant_id="assurance-tenant", passport_id=passport_id).count() == 1


def test_readiness_scoring_and_missing_proof_detection(client, db):
    headers = _headers_for(db)
    db.add(ComplianceParcel(id="ready-parcel", tenant_id="assurance-tenant", parcel_identifier="READY-1"))
    db.commit()
    passport_id = _create_passport(client, headers, parcel_ids=["ready-parcel"])
    missing = client.get(f"/v1/assurance/passports/{passport_id}/readiness", headers=headers).json()
    assert missing["status"] == "missing_proof"
    assert missing["missing_evidence"]
    assert missing["scope"]["readiness_package_only"] is True
    assert missing["scope"]["authority_submission"] is False

    for evidence_type, proof_domain in [
        ("water_budget", "water_proof"),
        ("water_measurement", "water_proof"),
        ("farm_boundary", "farm_summary"),
        ("risk_context", "risk_score"),
    ]:
        client.post(
            f"/v1/assurance/passports/{passport_id}/evidence",
            headers=headers,
            json={"evidence_type": evidence_type, "proof_domain": proof_domain, "file_ref": f"manual://{evidence_type}"},
        )
    input_response = client.post(
        f"/v1/assurance/passports/{passport_id}/input-applications",
        headers=headers,
        json={"application_type": "fertilizer", "product_name": "Compost tea", "quantity": 12, "unit": "gal"},
    )
    assert input_response.status_code == 201
    lot = client.post(
        f"/v1/assurance/passports/{passport_id}/harvest-lots",
        headers=headers,
        json={"lot_code": "LOT-2026-001", "crop": "tomatoes"},
    ).json()
    trace = client.post(
        f"/v1/assurance/passports/{passport_id}/traceability-events",
        headers=headers,
        json={"harvest_lot_id": lot["id"], "event_type": "packed", "payload": {"facility": "packing shed"}},
    )
    assert trace.status_code == 201

    ready = client.get(f"/v1/assurance/passports/{passport_id}/readiness", headers=headers).json()
    assert ready["status"] == "ready_for_review"
    assert ready["readiness_score"] == 100.0
    assert ready["missing_evidence"] == []


def test_passport_scope_prevents_cross_passport_proof_reuse(client, db):
    headers = _headers_for(db, "tenant-scope")
    db.add_all([
        ComplianceParcel(id="scope-parcel-a", tenant_id="tenant-scope", parcel_identifier="SCOPE-A"),
        ComplianceParcel(id="scope-parcel-b", tenant_id="tenant-scope", parcel_identifier="SCOPE-B"),
        ComplianceWell(id="scope-well-a", tenant_id="tenant-scope", parcel_id="scope-parcel-a", well_identifier="WELL-A"),
        ComplianceWell(id="scope-well-b", tenant_id="tenant-scope", parcel_id="scope-parcel-b", well_identifier="WELL-B"),
        ComplianceMeter(id="scope-meter-a", tenant_id="tenant-scope", well_id="scope-well-a", meter_identifier="M-A", measurement_method="meter"),
        ComplianceMeter(id="scope-meter-b", tenant_id="tenant-scope", well_id="scope-well-b", meter_identifier="M-B", measurement_method="meter"),
        ComplianceMeasurement(
            id="scope-measurement-a",
            tenant_id="tenant-scope",
            measurement_type="extraction",
            source_system="meter",
            truth_label="measured",
            source_timestamp=datetime(2026, 1, 1),
            value=12.0,
            unit="af",
            method="meter",
            quality_status="review_required",
            related_asset_type="meter",
            related_asset_id="scope-meter-a",
            reporting_period="2026",
        ),
        ComplianceWaterBudget(
            id="scope-budget-a",
            tenant_id="tenant-scope",
            allocation=100.0,
            extraction=12.0,
            irrigation_application=11.0,
            remaining_balance=88.0,
            projected_balance=80.0,
            threshold_status="review_required",
            water_source="groundwater",
            reporting_period="2026",
        ),
    ])
    db.commit()

    passport_a = _create_passport(client, headers, farm_name="Scoped Farm A", parcel_ids=["scope-parcel-a"], reporting_period="2026")
    passport_b = _create_passport(client, headers, farm_name="Scoped Farm B", parcel_ids=["scope-parcel-b"], reporting_period="2026")
    response = client.post(
        f"/v1/assurance/passports/{passport_a}/evidence",
        headers=headers,
        json={
            "evidence_type": "water_budget",
            "proof_domain": "water_proof",
            "file_ref": "compliance://water-budget/scope-budget-a",
            "metadata": {"water_budget_id": "scope-budget-a"},
        },
    )
    assert response.status_code == 201

    readiness_a = client.get(f"/v1/assurance/passports/{passport_a}/readiness", headers=headers).json()
    readiness_b = client.get(f"/v1/assurance/passports/{passport_b}/readiness", headers=headers).json()
    assert readiness_a["proof_counts"]["water_budget"] >= 1
    assert readiness_a["proof_counts"]["water_measurement"] >= 1
    assert readiness_b["proof_counts"].get("water_budget", 0) == 0
    assert readiness_b["proof_counts"].get("water_measurement", 0) == 0
    assert any(item["requirement_key"] == "water_budget_available" for item in readiness_b["missing_evidence"])

    export = client.post(f"/v1/assurance/passports/{passport_b}/exports", headers=headers, json={"export_type": "pdf"})
    assert export.status_code == 201, export.text
    payload = db.query(AssuranceExport).filter_by(tenant_id="tenant-scope", passport_id=passport_b).order_by(AssuranceExport.created_at.desc()).first().payload
    assert payload["farm_summary"]["parcels"][0]["id"] == "scope-parcel-b"
    assert payload["water_proof"]["water_budgets"] == []
    assert payload["water_proof"]["measurements"] == []


def test_missing_passport_scope_does_not_count_tenant_water_budget(client, db):
    headers = _headers_for(db, "tenant-missing-scope")
    db.add(ComplianceWaterBudget(
        id="unscoped-budget",
        tenant_id="tenant-missing-scope",
        allocation=50.0,
        extraction=10.0,
        irrigation_application=9.0,
        remaining_balance=40.0,
        projected_balance=35.0,
        threshold_status="review_required",
        water_source="groundwater",
        reporting_period="2026",
    ))
    db.commit()
    passport_id = _create_passport(client, headers, farm_name="Missing Scope Farm")

    readiness = client.get(f"/v1/assurance/passports/{passport_id}/readiness", headers=headers).json()
    assert readiness["status"] == "needs_scope_review"
    assert readiness["review_status"] == "needs_review"
    assert "parcel_ids" in readiness["scope"]["missing_scope"]
    assert readiness["proof_counts"].get("water_budget", 0) == 0


def test_pdf_export_generation_uses_audit_readiness_language(client, db):
    headers = _headers_for(db)
    passport_id = _create_passport(client, headers)
    response = client.post(f"/v1/assurance/passports/{passport_id}/exports", headers=headers, json={"export_type": "pdf"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "application/pdf"
    assert body["checksum"]
    assert b"%PDF" in base64.b64decode(body["content_base64"])[:16]
    assert "audit readiness" in body["disclaimer"].lower()
    assert "evidence package" in body["disclaimer"].lower()


def test_rule_pack_validation_and_catalog_have_no_california_api_names(client, db):
    headers = _headers_for(db)
    catalog = client.get("/v1/assurance/rule-packs", headers=headers)
    assert catalog.status_code == 200
    pack_ids = set(catalog.json()["rule_packs"].keys())
    assert {"waterops_generic_v0_1", "eudr_supplier_readiness_v0_1", "buyer_input_records_v0_1", "farm_finance_risk_pack_v0_1"} <= pack_ids
    assert all("california" not in pack_id for pack_id in pack_ids)

    invalid = client.post(
        "/v1/assurance/passports",
        headers=headers,
        json={"farm_name": "Bad Pack Farm", "rule_pack_ids": ["california_sgma_v0_1"]},
    )
    assert invalid.status_code == 422


def test_workbench_upload_can_attach_to_assurance_passport_and_persist(client, db):
    headers = _headers_for(db)
    passport_id = _create_passport(client, headers)
    created = client.post(
        "/v1/workbench/sessions",
        headers=headers,
        json={"mode": "uploaded", "assurance_passport_id": passport_id},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    uploaded = client.post(
        f"/v1/workbench/sessions/{session_id}/upload",
        headers=headers,
        files={"file": ("flow_meter.csv", BytesIO(b"timestamp,farm,block,meter_id,planned_m3,actual_m3,variance_percent\n2026-01-01,North,Block A,M-1,10,10,0\n"), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    workbench_engine.SESSIONS.pop(session_id, None)

    fetched = client.get(f"/v1/workbench/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["artifacts"][0]["filename"] == "flow_meter.csv"
    evidence = db.query(AssuranceEvidenceArtifact).filter_by(tenant_id="assurance-tenant", passport_id=passport_id, workbench_artifact_id=uploaded.json()["artifact_id"]).one()
    assert evidence.source_system == "workbench_upload"
    assert evidence.evidence_type == "water_measurement"


def test_agent_triage_returns_grounded_assurance_workflow(client, db):
    headers = _headers_for(db, "tenant-agent")
    db.add(ComplianceParcel(id="agent-parcel", tenant_id="tenant-agent", parcel_identifier="AGENT-1"))
    db.commit()
    passport_id = _create_passport(client, headers, farm_name="Agent Farm", parcel_ids=["agent-parcel"])

    response = client.post(f"/v1/agents/assurance/passports/{passport_id}/triage", headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workflow_type"] == "assurance_audit"
    assert body["passport_id"] == passport_id
    assert body["result"]["truth_constraints"]
    assert "certification" in body["result"]["truth_constraints"][0]
    assert body["result"]["missing_proof"]
    assert body["proposed_actions"]
    assert db.query(AgentWorkflowRun).filter_by(tenant_id="tenant-agent", passport_id=passport_id).count() == 1

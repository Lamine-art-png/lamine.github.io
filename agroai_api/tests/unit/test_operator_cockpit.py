from __future__ import annotations

from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.block import Block
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.models.telemetry import Telemetry


def _auth_workspace(db, *, email="operator@example.com", org_id="org-cockpit", workspace_id="workspace-cockpit"):
    user = User(
        id=f"user-{org_id}",
        email=email,
        name="Operator",
        password_hash="test",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    org = Organization(id=org_id, name="Cockpit Farms", slug=org_id, owner_user_id=user.id, plan="pro", subscription_status="active")
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(id=workspace_id, organization_id=org.id, name="Daily Ops", crop="Almonds", region="California", mode="live")
    db.add_all([user, org, membership, workspace])
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": "owner"})
    return org, workspace, {"Authorization": f"Bearer {token}"}


def _seed_real_data(db, org_id: str, workspace_id: str):
    connection = ConnectorConnection(
        id="conn-wiseconn",
        tenant_id=org_id,
        workspace_id=workspace_id,
        provider="wiseconn",
        display_name="WiseConn",
        status="connected",
        mode="api_credentials",
        credentials_ref="vault:wiseconn",
        last_sync_at=datetime.utcnow(),
    )
    stale = ConnectorConnection(
        id="conn-dropbox",
        tenant_id=org_id,
        workspace_id=workspace_id,
        provider="dropbox",
        display_name="Dropbox",
        status="needs_credentials",
        mode="oauth",
        config_json={"oauth_code_present": True, "oauth_code": "raw-secret-code", "api_secret": "secret-value"},
    )
    source = DataSource(
        id="source-flow",
        tenant_id=org_id,
        workspace_id=workspace_id,
        connector_connection_id=connection.id,
        source_type="irrigation_controller_export",
        provider="wiseconn",
        filename="north-ranch-flow.csv",
        raw_text="Field: North Ranch Block A flow gallons ET weather compliance meter",
        metadata_json={"field": "North Ranch", "block": "Block A", "crop": "Almonds"},
        status="parsed",
    )
    orphan_source = DataSource(
        id="source-orphan",
        tenant_id=org_id,
        workspace_id=workspace_id,
        provider="manual_csv",
        source_type="csv",
        filename="duplicate.csv",
        status="parsed",
    )
    evidence = EvidenceRecord(
        id="evidence-flow",
        tenant_id=org_id,
        workspace_id=workspace_id,
        data_source_id=source.id,
        connector_connection_id=connection.id,
        evidence_type="irrigation_flow",
        field_id="north-ranch",
        block_id="block-a",
        occurred_at=datetime.utcnow() - timedelta(hours=1),
        title="North Ranch irrigation flow",
        summary="Block A flow record includes gallons applied and controller runtime.",
        value_json={"gallons": 12000},
        units="gallons",
        confidence=0.88,
        quality_status="usable",
        citation_label="WiseConn export",
        metadata_json={"field": "North Ranch", "block": "Block A", "crop": "Almonds"},
    )
    block = Block(
        id="block-a",
        tenant_id=org_id,
        name="Block A",
        area_ha=10,
        crop_type="Almonds",
        soil_type="loam",
        config={"workspace_id": workspace_id, "source": "operator_upload"},
    )
    telemetry = Telemetry(
        id="telemetry-et",
        tenant_id=org_id,
        block_id=block.id,
        type="et0",
        timestamp=datetime.utcnow(),
        value=4.2,
        unit="mm/day",
        source="openet",
        meta_data={"workspace_id": workspace_id},
    )
    failed_job = IngestionJob(
        id="job-failed",
        tenant_id=org_id,
        workspace_id=workspace_id,
        connector_connection_id=stale.id,
        job_type="sync",
        status="failed",
        error="Token exchange pending",
    )
    db.add_all([connection, stale, source, orphan_source, evidence, block, telemetry, failed_job])
    db.commit()


def test_readiness_summary_returns_200_and_empty_workspace_sample_mode(client, db):
    _org, workspace, headers = _auth_workspace(db)
    response = client.get(f"/v1/readiness/summary?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["sample_mode"] is True
    assert body["readiness_level"] == "blocked"


def test_real_connector_and_evidence_data_returns_sample_mode_false(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-real", workspace_id="workspace-real")
    _seed_real_data(db, org.id, workspace.id)
    response = client.get(f"/v1/readiness/summary?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["sample_mode"] is False
    assert body["connected_sources"] >= 1
    assert "irrigation_controller" in body["present_source_types"]


def test_exceptions_detect_setup_required_connector(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-exceptions", workspace_id="workspace-exceptions")
    _seed_real_data(db, org.id, workspace.id)
    response = client.get(f"/v1/exceptions?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    titles = [row["title"] for row in response.json()["exceptions"]]
    assert any("Dropbox" in title for title in titles)
    assert response.json()["counts_by_severity"]


def test_field_intelligence_groups_evidence_by_field_block_crop(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-fields", workspace_id="workspace-fields")
    _seed_real_data(db, org.id, workspace.id)
    response = client.get(f"/v1/fields/intelligence?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    fields = response.json()["fields"]
    north = next(row for row in fields if row["field_name"] == "North Ranch")
    assert north["crop"] == "Almonds"
    assert north["evidence_count"] == 1
    assert "wiseconn" in north["connected_providers"]


def test_decision_workbench_returns_structured_decision_with_missing_evidence(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-decisions", workspace_id="workspace-decisions")
    _seed_real_data(db, org.id, workspace.id)
    response = client.get(f"/v1/decisions/workbench?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    decision = response.json()["decisions"][0]
    assert decision["approval_status"] == "needs_review"
    assert "missing_evidence" in decision
    assert "operator_instructions" in decision


def test_report_factory_returns_structured_json_for_all_report_types(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-reports", workspace_id="workspace-reports")
    _seed_real_data(db, org.id, workspace.id)
    for report_type in [
        "water_use_summary",
        "compliance_packet",
        "exception_report",
        "executive_brief",
        "grower_recommendation",
    ]:
        response = client.post(
            "/v1/reports/factory",
            headers=headers,
            json={"workspace_id": workspace.id, "report_type": report_type, "audience": "owner"},
        )
        assert response.status_code == 200, response.text
        report = response.json()["report"]
        assert report["report_type"] == report_type
        assert isinstance(report["evidence_appendix"], list)


def test_operator_cockpit_does_not_return_secret_values_or_raw_oauth_codes(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-redaction", workspace_id="workspace-redaction")
    _seed_real_data(db, org.id, workspace.id)
    responses = [
        client.get(f"/v1/readiness/summary?workspace_id={workspace.id}", headers=headers),
        client.get(f"/v1/exceptions?workspace_id={workspace.id}", headers=headers),
        client.post(
            "/v1/reports/factory",
            headers=headers,
            json={"workspace_id": workspace.id, "report_type": "exception_report"},
        ),
    ]
    payload = "\n".join(response.text for response in responses)
    assert "raw-secret-code" not in payload
    assert "secret-value" not in payload

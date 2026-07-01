from __future__ import annotations

from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.block import Block
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.models.telemetry import Telemetry


def _auth_workspace(db, *, email="loop@example.com", org_id="org-loop", workspace_id="workspace-loop"):
    user = User(
        id=f"user-{org_id}",
        email=email,
        name="Loop User",
        password_hash="test",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    org = Organization(id=org_id, name="Loop Farms", slug=org_id, owner_user_id=user.id, plan="pro", subscription_status="active")
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(id=workspace_id, organization_id=org.id, name="Command Center", crop="Almonds", region="California", mode="live")
    db.add_all([user, org, membership, workspace])
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": "owner"})
    return org, workspace, {"Authorization": f"Bearer {token}"}


def _seed_loop_data(db, org_id: str, workspace_id: str):
    connection = ConnectorConnection(
        id="conn-wiseconn-loop",
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
        id="conn-weather-loop",
        tenant_id=org_id,
        workspace_id=workspace_id,
        provider="weather",
        display_name="Weather",
        status="needs_credentials",
        mode="provider_api",
        config_json={"oauth_code": "top-secret-code", "api_secret": "hidden-secret"},
    )
    source = DataSource(
        id="source-loop",
        tenant_id=org_id,
        workspace_id=workspace_id,
        connector_connection_id=connection.id,
        source_type="irrigation_controller_export",
        provider="wiseconn",
        filename="block-a.csv",
        raw_text="Field North Ranch Block A runtime gallons meter weather compliance",
        metadata_json={"field": "North Ranch", "block": "Block A", "crop": "Almonds"},
        status="parsed",
    )
    block = Block(
        id="block-a-loop",
        tenant_id=org_id,
        name="Block A",
        area_ha=10,
        crop_type="Almonds",
        soil_type="loam",
        water_budget_allocated=1000,
        water_budget_used=820,
        config={"workspace_id": workspace_id, "source": "operator_upload"},
    )
    evidence = EvidenceRecord(
        id="evidence-loop",
        tenant_id=org_id,
        workspace_id=workspace_id,
        data_source_id=source.id,
        connector_connection_id=connection.id,
        evidence_type="irrigation_flow",
        field_id="north-ranch",
        block_id=block.id,
        occurred_at=datetime.utcnow() - timedelta(hours=2),
        title="North Ranch flow record",
        summary="Controller flow and gallons applied captured for Block A.",
        value_json={"gallons": 18900},
        units="gallons",
        confidence=0.85,
        quality_status="usable",
        citation_label="WiseConn export",
        metadata_json={"field": "North Ranch", "block": "Block A", "crop": "Almonds"},
    )
    telemetry = Telemetry(
        id="telemetry-loop",
        tenant_id=org_id,
        block_id=block.id,
        type="flow",
        timestamp=datetime.utcnow(),
        value=18.4,
        unit="gpm",
        source="wiseconn",
        meta_data={"workspace_id": workspace_id},
    )
    failed_job = IngestionJob(
        id="job-loop",
        tenant_id=org_id,
        workspace_id=workspace_id,
        connector_connection_id=stale.id,
        job_type="sync",
        status="failed",
        error="Reconnect weather source",
    )
    db.add_all([connection, stale, source, block, evidence, telemetry, failed_job])
    db.commit()


def test_command_center_returns_200(client, db):
    org, workspace, headers = _auth_workspace(db)
    _seed_loop_data(db, org.id, workspace.id)
    response = client.get(f"/v1/field-ops/command-center?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["today_priority"]["recommended_action"]
    assert isinstance(body["field_queue"], list)


def test_task_generation_works_from_missing_evidence(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-tasks", workspace_id="workspace-loop-tasks")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.get(f"/v1/field-ops/tasks?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert any(task["created_from"] == "missing_evidence" for task in tasks)


def test_field_update_creates_structured_evidence(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-update", workspace_id="workspace-loop-update")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.post(
        "/v1/field-ops/field-update",
        headers=headers,
        json={
            "workspace_id": workspace.id,
            "field_name": "North Ranch",
            "block": "Block A",
            "update_text": "Observed stressed trees near west valve.",
            "event_type": "issue",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_evidence"]
    assert body["recommended_next_action"]


def test_field_message_parser_extracts_values(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-message", workspace_id="workspace-loop-message")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.post(
        "/v1/field-ops/field-message",
        headers=headers,
        json={
            "workspace_id": workspace.id,
            "message": "Block A ran for 45 minutes, meter read 18,900 gallons, almonds looked stressed near west valve.",
            "sender_role": "operator",
            "channel": "portal",
            "field_hint": "North Ranch",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    extracted = body["extracted_fields"]
    assert extracted["duration_minutes"] == 45.0
    assert extracted["water_gallons"] == 18900.0
    assert extracted["block"] == "Block A"


def test_autopilot_report_returns_structured_report(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-report", workspace_id="workspace-loop-report")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.post(
        "/v1/field-ops/autopilot-report",
        headers=headers,
        json={"workspace_id": workspace.id, "audience": "owner", "scope": "today"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["title"]
    assert body["pdf_ready"] is True
    assert body["pdf_request"]["report_type"]


def test_audit_trail_returns_events(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-audit", workspace_id="workspace-loop-audit")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.get(f"/v1/field-ops/audit-trail?workspace_id={workspace.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["events"]


def test_field_ops_redacts_secrets_and_oauth_codes(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-redact", workspace_id="workspace-loop-redact")
    _seed_loop_data(db, org.id, workspace.id)
    responses = [
        client.get(f"/v1/field-ops/command-center?workspace_id={workspace.id}", headers=headers),
        client.get(f"/v1/field-ops/audit-trail?workspace_id={workspace.id}", headers=headers),
        client.post(
            "/v1/field-ops/autopilot-report",
            headers=headers,
            json={"workspace_id": workspace.id, "audience": "agency", "scope": "compliance"},
        ),
    ]
    payload = "\n".join(response.text for response in responses)
    assert "top-secret-code" not in payload
    assert "hidden-secret" not in payload


def test_field_ops_uses_real_data_not_fake_customer_evidence(client, db):
    org, workspace, headers = _auth_workspace(db, org_id="org-loop-real", workspace_id="workspace-loop-real")
    _seed_loop_data(db, org.id, workspace.id)
    response = client.get(f"/v1/field-ops/command-center?workspace_id={workspace.id}", headers=headers)
    body = response.json()
    assert response.status_code == 200
    assert body["sample_mode"] is False
    assert body["field_queue"][0]["field_name"]

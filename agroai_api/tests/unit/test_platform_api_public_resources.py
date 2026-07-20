from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.models.operational_records import ConnectorConnection, IngestionJob
from app.models.platform_api import PlatformApiUsageEvent
from app.models.platform_product import PlatformLiveAccessRequest, PlatformProgramEnrollment, PlatformRequestLog
from app.models.saas import ManagedEntity
from app.models.task_outbox import TaskOutbox
from tests.unit.test_platform_api_foundation import _project_and_key


PUBLIC_SCOPES = [
    "projects:read",
    "fields:read",
    "fields:write",
    "sources:read",
    "sources:write",
    "observations:read",
    "observations:write",
    "recommendations:read",
    "recommendations:write",
    "reports:read",
    "reports:write",
    "jobs:read",
    "usage:read",
]


def _enable_api(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED", False)
    monkeypatch.setattr(settings, "APP_ENV", "test")


def test_repeated_client_request_id_never_deduplicates_get_metering(
    client,
    db,
    monkeypatch,
):
    _enable_api(monkeypatch)
    _user, organization, _workspace, project, _service_account, _key, plaintext = (
        _project_and_key(db)
    )
    headers = {
        "Authorization": f"Bearer {plaintext}",
        "X-Request-Id": "client-correlation-repeat",
    }

    first = client.get("/v1/platform/me", headers=headers)
    second = client.get("/v1/platform/me", headers=headers)
    cross_route = client.get("/v1/platform/providers", headers=headers)

    assert first.status_code == second.status_code == cross_route.status_code == 200
    server_request_ids = {
        first.headers["x-request-id"],
        second.headers["x-request-id"],
        cross_route.headers["x-request-id"],
    }
    assert len(server_request_ids) == 3
    assert "client-correlation-repeat" not in server_request_ids

    db.expire_all()
    logs = (
        db.query(PlatformRequestLog)
        .filter(
            PlatformRequestLog.organization_id == organization.id,
            PlatformRequestLog.api_project_id == project.id,
            PlatformRequestLog.client_correlation_id
            == "client-correlation-repeat",
        )
        .all()
    )
    assert len(logs) == 3
    assert {row.request_id for row in logs} == server_request_ids
    assert len({row.operation_id for row in logs}) == 2

    usage = (
        db.query(PlatformApiUsageEvent)
        .filter(
            PlatformApiUsageEvent.organization_id == organization.id,
            PlatformApiUsageEvent.api_project_id == project.id,
            PlatformApiUsageEvent.request_id.in_(server_request_ids),
        )
        .all()
    )
    assert len(usage) == 3
    assert len({row.idempotency_key for row in usage}) == 3
    assert all(
        (row.metadata_json or {}).get("client_correlation_id")
        == "client-correlation-repeat"
        for row in usage
    )


def test_field_lifecycle_is_idempotent_isolated_and_request_logs_are_metadata_only(client, db, monkeypatch):
    _enable_api(monkeypatch)
    _user, organization, _workspace, project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=PUBLIC_SCOPES,
    )
    _other_user, other_organization, _other_workspace, _other_project, _other_sa, _other_key, other_plaintext = _project_and_key(
        db,
        scopes=PUBLIC_SCOPES,
    )
    headers = {
        "Authorization": f"Bearer {plaintext}",
        "Idempotency-Key": "field-create-logical-1",
        "X-Request-Id": "req-field-create-1",
    }
    payload = {
        "name": "Synthetic North Field",
        "crop": "tomato",
        "area_hectares": 12.5,
        "metadata": {"source": "sdk-contract-test"},
    }
    created = client.post("/v1/platform/fields", headers=headers, json=payload)
    assert created.status_code == 201
    field_id = created.json()["field"]["id"]
    replay = client.post(
        "/v1/platform/fields",
        headers={**headers, "X-Request-Id": "req-field-create-replay"},
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["field"]["id"] == field_id
    assert db.query(ManagedEntity).filter_by(
        organization_id=organization.id,
        entity_type="platform_field",
    ).count() == 1

    conflict = client.post(
        "/v1/platform/fields",
        headers={**headers, "X-Request-Id": "req-field-create-conflict"},
        json={**payload, "name": "Different payload"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    second = client.post(
        "/v1/platform/fields",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": "field-create-logical-2",
        },
        json={**payload, "name": "Synthetic South Field"},
    )
    assert second.status_code == 201
    first_page = client.get(
        "/v1/platform/fields?limit=1",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert first_page.status_code == 200
    assert first_page.json()["has_more"] is True
    assert first_page.json()["next_cursor"]
    second_page = client.get(
        f"/v1/platform/fields?limit=1&cursor={first_page.json()['next_cursor']}",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert second_page.status_code == 200
    assert second_page.json()["items"][0]["id"] != first_page.json()["items"][0]["id"]

    denied = client.get(
        f"/v1/platform/fields/{field_id}",
        headers={"Authorization": f"Bearer {other_plaintext}"},
    )
    assert denied.status_code == 404
    assert other_organization.id != organization.id

    archived = client.delete(
        f"/v1/platform/fields/{field_id}",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": "field-archive-logical-1",
        },
    )
    assert archived.status_code == 200
    replay_archive = client.delete(
        f"/v1/platform/fields/{field_id}",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": "field-archive-logical-1",
        },
    )
    assert replay_archive.json() == archived.json()

    logs = db.query(PlatformRequestLog).filter_by(organization_id=organization.id).all()
    assert logs
    assert all(not hasattr(row, "request_body") and not hasattr(row, "authorization") for row in logs)
    assert all(row.api_project_id == project.id for row in logs)


def test_recommendation_job_has_one_durable_outbox_entry_per_logical_request(client, db, monkeypatch):
    _enable_api(monkeypatch)
    _user, organization, _workspace, _project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=PUBLIC_SCOPES,
    )
    field = ManagedEntity(
        organization_id=organization.id,
        workspace_id=_workspace.id,
        entity_type="platform_field",
        display_name="Recommendation Field",
        status="active",
        metadata_json={"api_project_id": _project.id, "synthetic": True},
    )
    db.add(field)
    db.commit()
    headers = {
        "Authorization": f"Bearer {plaintext}",
        "Idempotency-Key": "recommendation-logical-1",
    }
    payload = {
        "field_id": field.id,
        "objective": "evidence-backed irrigation timing",
        "evidence_ids": [],
        "parameters": {"physical_execution": False},
    }
    first = client.post("/v1/platform/recommendations", headers=headers, json=payload)
    second = client.post("/v1/platform/recommendations", headers=headers, json=payload)
    assert first.status_code == 202
    assert second.json()["job"]["id"] == first.json()["job"]["id"]
    job_id = first.json()["job"]["id"]
    assert db.query(IngestionJob).filter_by(id=job_id, tenant_id=organization.id).count() == 1
    assert db.query(TaskOutbox).filter_by(job_id=job_id, tenant_id=organization.id).count() == 1


def test_provider_sync_is_live_only_org_isolated_idempotent_and_truthful(client, db, monkeypatch):
    _enable_api(monkeypatch)
    scopes = ["projects:read", "connectors:read", "connectors:sync"]
    _user, organization, workspace, _project, _service_account, _key, plaintext = _project_and_key(
        db,
        scopes=scopes,
        environment="live",
    )
    connection = ConnectorConnection(
        tenant_id=organization.id,
        workspace_id=workspace.id,
        provider="google_drive",
        display_name="Approved Drive connection",
        status="connected",
        mode="oauth",
        required_plan="professional",
        config_json={},
        credentials_ref="connector-vault-record-id",
    )
    enrollment = db.query(PlatformProgramEnrollment).filter_by(organization_id=organization.id).one()
    enrollment.billing_mode = "contract"
    db.add(
        PlatformLiveAccessRequest(
            organization_id=organization.id,
            requested_by_user_id=_user.id,
            api_project_id=_project.id,
            status="approved",
            intended_production_use="Authorized connector synchronization",
            expected_users="10",
            expected_volume="1000",
            expected_peak_rate="5 requests per second",
            data_categories_json=["connector data"],
            provider_dependencies_json=["google_drive"],
            geographic_regions_json=["United States"],
            security_contact=_user.email,
            incident_contact=_user.email,
            cidr_strategy="Fixed corporate egress",
            data_retention="30 days",
            billing_plan="enterprise_contract",
            decided_at=datetime.utcnow(),
        )
    )
    db.add(connection)
    db.commit()
    headers = {
        "Authorization": f"Bearer {plaintext}",
        "Idempotency-Key": "provider-sync-logical-1",
    }
    status_response = client.get(
        "/v1/platform/providers/google_drive",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["connections"][0]["id"] == connection.id
    assert "credentials_ref" not in status_response.json()["connections"][0]

    first = client.post(
        "/v1/platform/providers/google_drive/sync",
        headers=headers,
        json={"connection_id": connection.id},
    )
    second = client.post(
        "/v1/platform/providers/google_drive/sync",
        headers=headers,
        json={"connection_id": connection.id},
    )
    assert first.status_code == 202
    assert second.json()["job"]["id"] == first.json()["job"]["id"]
    job_id = first.json()["job"]["id"]
    assert db.query(IngestionJob).filter_by(id=job_id, tenant_id=organization.id).count() == 1
    assert db.query(TaskOutbox).filter_by(job_id=job_id, tenant_id=organization.id).count() == 1

    earthdaily = client.post(
        "/v1/platform/providers/earthdaily/sync",
        headers={**headers, "Idempotency-Key": "earthdaily-sync"},
        json={"connection_id": connection.id},
    )
    assert earthdaily.status_code == 409
    assert earthdaily.json()["readiness"] == "awaiting_partner_contract"

    _test_user, _test_org, _test_workspace, _test_project, _test_sa, _test_key, test_plaintext = _project_and_key(
        db,
        scopes=scopes,
        environment="test",
    )
    test_denied = client.post(
        "/v1/platform/providers/google_drive/sync",
        headers={
            "Authorization": f"Bearer {test_plaintext}",
            "Idempotency-Key": "test-provider-sync",
        },
        json={"connection_id": connection.id},
    )
    assert test_denied.status_code == 403
    assert test_denied.json()["code"] == "live_provider_access_requires_live_key"

from __future__ import annotations

import json

from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import PlatformProductAuditEvent
from tests.unit.test_platform_api_foundation import _project_and_key


def _headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True)


def test_playground_is_fail_closed_when_test_projects_are_disabled(client, db, monkeypatch):
    user, org, _workspace, project, *_ = _project_and_key(db, environment="test")
    org.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", False)

    response = client.post(
        "/v1/platform/developer/playground/execute",
        headers=_headers(user),
        json={"project_id": project.id, "operation": "sandbox_summary"},
    )

    assert response.status_code == 404


def test_playground_executes_synthetic_test_data_without_browser_key(client, db, monkeypatch):
    user, org, _workspace, project, *_ = _project_and_key(db, environment="test")
    org.verification_status = "approved"
    db.commit()
    _enable(monkeypatch)

    response = client.post(
        "/v1/platform/developer/playground/execute",
        headers=_headers(user),
        json={"project_id": project.id, "operation": "list_fields"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "portal_session_synthetic"
    assert payload["environment"] == "test"
    assert payload["synthetic"] is True
    assert payload["physical_execution"] is False
    assert payload["provider_credentials"] is False
    assert payload["credit_cost"] == 0
    assert payload["request"]["path"] == "/v1/platform/fields"
    assert payload["response"]["status"] == 200
    assert payload["response"]["body"]["has_more"] is False
    assert all(item["synthetic"] is True for item in payload["response"]["body"]["items"])

    serialized = json.dumps(payload).lower()
    assert "plaintext_key" not in serialized
    assert "authorization: bearer agro_" not in serialized
    assert "$agroai_api_key" in payload["code"]["curl"].lower()
    assert db.query(PlatformProductAuditEvent).filter_by(
        organization_id=org.id,
        event_type="platform.playground.executed",
        subject_id=project.id,
    ).count() == 1


def test_playground_refuses_live_projects_even_when_live_access_exists(client, db, monkeypatch):
    user, org, _workspace, project, *_ = _project_and_key(db, environment="live")
    org.verification_status = "approved"
    db.commit()
    _enable(monkeypatch)

    response = client.post(
        "/v1/platform/developer/playground/execute",
        headers=_headers(user),
        json={"project_id": project.id, "operation": "sandbox_summary"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "playground_test_project_required"


def test_playground_is_organization_scoped(client, db, monkeypatch):
    first_user, first_org, _workspace, first_project, *_ = _project_and_key(db, environment="test")
    second_user, second_org, *_ = _project_and_key(db, environment="test")
    first_org.verification_status = "approved"
    second_org.verification_status = "approved"
    db.commit()
    _enable(monkeypatch)

    response = client.post(
        "/v1/platform/developer/playground/execute",
        headers=_headers(second_user),
        json={"project_id": first_project.id, "operation": "sandbox_summary"},
    )

    assert response.status_code == 404


def test_playground_operation_catalog_is_keyless_and_read_only(client, db, monkeypatch):
    user, org, *_ = _project_and_key(db, environment="test")
    org.verification_status = "approved"
    db.commit()
    _enable(monkeypatch)

    response = client.get(
        "/v1/platform/developer/playground/operations",
        headers=_headers(user),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["permanent_api_key_in_browser"] is False
    assert payload["live_projects_allowed"] is False
    assert payload["physical_execution"] is False
    assert payload["operations"]
    assert {item["method"] for item in payload["operations"]} == {"GET"}

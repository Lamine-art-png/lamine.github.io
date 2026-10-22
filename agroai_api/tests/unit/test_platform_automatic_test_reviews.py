"""Automatic, audited TEST-only application decisions."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import PlatformApiApplication, PlatformProgramEnrollment, PlatformProductAuditEvent
from app.platform_api.automatic_application_review import adjudicate_submitted_test_applications
from app.models.saas import User, Organization, OrganizationMembership
from app.models.platform_api import ApiProject, ApiServiceAccount
from app.platform_api.keys import create_platform_key
from tests.unit.test_platform_api_product import _application_payload


def _setup(db, monkeypatch):
    user = User(
        email=f"test-review-{uuid4().hex[:12]}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Test Review Applicant",
        slug=f"test-review-{uuid4().hex[:12]}",
        owner_user_id=user.id,
        verification_status="approved",
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(
        organization_id=org.id, user_id=user.id, role="owner", status="active",
    ))
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_AUTOMATED_TEST_REVIEWS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False)
    return user, org, {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}


def test_eligible_user_gets_bounded_test_not_live(client, db, monkeypatch):
    user, org, headers = _setup(db, monkeypatch)
    response = client.post("/v1/platform/applications", headers=headers, json=_application_payload(user.email))
    assert response.status_code == 202
    application = response.json()["application"]
    assert application["status"] == "approved"
    enrollment = db.query(PlatformProgramEnrollment).filter_by(
        organization_id=org.id, program="developer_private_beta"
    ).one()
    assert enrollment.status == "active"
    assert enrollment.allowed_environments_json == ["test"]
    assert enrollment.maximum_live_projects == 0
    assert enrollment.maximum_keys == 2
    assert enrollment.billing_mode == "none"
    assert all("execute" not in s and "sync" not in s for s in enrollment.default_scopes_json)
    audit = db.query(PlatformProductAuditEvent).filter_by(
        subject_id=application["id"], event_type="platform.application.auto_approved"
    ).all()
    assert len(audit) == 1
    # Repeated status checks neither issue keys nor create another entitlement.
    assert client.get("/v1/platform/applications", headers=headers).status_code == 200
    assert db.query(PlatformProductAuditEvent).filter_by(
        subject_id=application["id"], event_type="platform.application.auto_approved"
    ).count() == 1


def test_live_requests_are_decided_without_live_privileges(client, db, monkeypatch):
    user, org, headers = _setup(db, monkeypatch)
    request = _application_payload(user.email)
    request["requested_environment"] = "live"
    res = client.post("/v1/platform/applications", headers=headers, json=request)
    assert res.status_code == 202
    assert res.json()["application"]["status"] == "rejected"
    assert db.query(PlatformProgramEnrollment).filter_by(
        organization_id=org.id, program="developer_private_beta"
    ).count() == 0


def test_reconciles_old_pending_requests_and_respects_suspensions(client, db, monkeypatch):
    user, org, headers = _setup(db, monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_AUTOMATED_TEST_REVIEWS_ENABLED", False)
    res = client.post("/v1/platform/applications", headers=headers, json=_application_payload(user.email))
    app_id = res.json()["application"]["id"]
    assert res.json()["application"]["status"] == "submitted"
    monkeypatch.setattr(settings, "PLATFORM_API_AUTOMATED_TEST_REVIEWS_ENABLED", True)
    assert adjudicate_submitted_test_applications(db, organization_id=org.id) == 1
    assert db.get(PlatformApiApplication, app_id).status == "approved"
    assert adjudicate_submitted_test_applications(db, organization_id=org.id) == 0
    # An operator suspension must never be lifted by later applications.
    enrollment = db.query(PlatformProgramEnrollment).filter_by(
        organization_id=org.id, program="developer_private_beta"
    ).one()
    enrollment.status = "suspended"
    db.commit()
    payload = _application_payload(user.email)
    followup = client.post("/v1/platform/applications", headers=headers, json=payload)
    assert followup.status_code == 202
    assert followup.json()["application"]["status"] == "rejected"
    assert enrollment.status == "suspended"


def test_existing_live_intelligence_does_not_consume_test_quotas(client, db, monkeypatch):
    user, org, headers = _setup(db, monkeypatch)
    application = client.post(
        "/v1/platform/applications", headers=headers, json=_application_payload(user.email)
    )
    assert application.status_code == 202
    assert application.json()["application"]["status"] == "approved"
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", False)

    live = ApiProject(
        organization_id=org.id, name="AGRO-AI Intelligence", slug="intelligence",
        environment="live", status="active", created_by_user_id=user.id,
    )
    db.add(live)
    db.flush()
    live_service = ApiServiceAccount(
        organization_id=org.id, api_project_id=live.id, name="live-advisory",
        status="active", scopes=["projects:read"], created_by_user_id=user.id,
    )
    db.add(live_service)
    db.flush()
    create_platform_key(
        db, project=live, service_account=live_service, name="existing advisory key",
        scopes=["projects:read"], created_by_user_id=user.id,
    )
    db.commit()

    # The one-project TEST cap must apply only to TEST, not the existing LIVE project.
    response = client.post(
        "/v1/platform/developer/projects", headers=headers,
        json={"name": "dmrv-test", "environment": "test"},
    )
    assert response.status_code == 201, response.text
    test_id = response.json()["project"]["id"]
    assert response.json()["project"]["environment"] == "test"

    # Test SA/key quotas are likewise separate from the LIVE advisory credential.
    service = client.post(
        f"/v1/platform/developer/projects/{test_id}/service-accounts",
        headers=headers, json={"name": "dmrv-test-service", "scopes": ["projects:read"]},
    )
    assert service.status_code == 201, service.text
    sa_id = service.json()["service_account"]["id"]
    key = client.post(
        f"/v1/platform/developer/service-accounts/{sa_id}/keys",
        headers=headers, json={"name": "dmrv-test-key", "scopes": ["projects:read"]},
    )
    assert key.status_code == 201, key.text
    assert key.json()["plaintext_key"].startswith("agro_test_")

    # A second TEST project must still be rejected. No LIVE access was granted.
    again = client.post(
        "/v1/platform/developer/projects", headers=headers,
        json={"name": "dmrv-test-2", "environment": "test"},
    )
    assert again.status_code == 409, again.text
    assert db.get(ApiProject, live.id).status == "active"

"""True front-door developer journey on real PostgreSQL (item 5).

Proves the claimed self-service path through the REAL auth endpoints with NO
database seeding of verified-user / approved-organization / program-enrollment
state: register -> automated verification engine -> email token (captured via a
safe test fixture) -> confirm -> organization approved -> login -> accept current
Platform developer terms -> AUTOMATIC TEST enrollment (no manual review) ->
project -> service account -> agro_test_ key -> first Platform API request.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")

STRONG = {
    "password": "strong-password-2026",
    "name": "Jane Farmer",
    "organization_type": "farm_or_grower",
    "professional_role": "Farm operations manager",
    "phone_number": "+1 415 555 0199",
    "website_url": "https://valleyorchards.com",
    "professional_profile_url": "https://www.linkedin.com/in/jane-farmer",
    "country": "United States",
    "operating_region": "California Central Valley",
    "acres_or_sites": "2,500 acres across four farms",
    "primary_crops": "Almonds and pistachios",
    "intended_use": "We manage irrigated almond and pistachio fields and need AGRO-AI to connect field evidence, improve irrigation decisions, and produce operating reports.",
    "planned_data_sources": "WiseConn, John Deere, PDFs, spreadsheets, and weather records",
    "workspace_name": "Central Valley operations",
    "crop": "Almonds and pistachios",
    "region": "California Central Valley",
}


def test_real_front_door_registration_through_self_service_first_api_call(monkeypatch):
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app
    from app.models.saas import Organization
    from app.models.platform_product import PlatformProgramEnrollment, PlatformProductAuditEvent, PlatformTermsDocument
    import app.api.v1.auth as auth_module

    monkeypatch.setattr(settings, "ACCOUNT_VERIFICATION_MODE", "enforce", raising=False)
    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
                 "PLATFORM_API_TEST_PROJECTS_ENABLED", "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED",
                 "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)

    Session = sessionmaker(bind=create_engine(POSTGRES_URL, pool_pre_ping=True), expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Safe email-delivery fixture: capture the plaintext verification token
    # instead of sending an email. This is the only override for THIS journey.
    captured: dict[str, str] = {}
    original_send = auth_module.send_or_log_verification

    def _capture(db, user, token, *args, **kwargs):
        captured["token"] = token
        return {"delivery": "captured", "provider_configured": True}

    monkeypatch.setattr(auth_module, "send_or_log_verification", _capture)

    # Publish a current developer terms document (control-plane legal catalog).
    s = uuid.uuid4().hex[:8]
    tv = f"v-{s}"
    db = Session()
    try:
        db.add(PlatformTermsDocument(document_type="api_terms", version=tv, status="approved_effective",
                                     content_digest="a" * 64, effective_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    try:
        email = f"jane.farmer.{s}@gmail.com"
        registration = {**STRONG, "email": email, "organization_name": f"Valley Orchards {s} LLC"}

        # 1. Register through the real endpoint -> automated verification engine.
        reg = client.post("/v1/auth/register", json=registration)
        assert reg.status_code == 201, reg.text
        org_id = reg.json()["current_organization"]["id"]
        assert reg.json()["organization_verification"]["status"] == "preapproved_pending_email"
        db = Session()
        try:
            assert db.get(Organization, org_id).verification_status == "preapproved_pending_email"
        finally:
            db.close()
        assert "token" in captured  # produced via the safe fixture

        # 2. Confirm the real email verification token -> organization approved.
        confirm = client.post("/v1/auth/email-verification/confirm", json={"token": captured["token"]})
        assert confirm.status_code == 200, confirm.text
        db = Session()
        try:
            assert db.get(Organization, org_id).verification_status == "approved"
        finally:
            db.close()

        # 3. Login succeeds and yields an org-scoped session.
        login = client.post("/v1/auth/login", json={"email": email, "password": STRONG["password"]})
        assert login.status_code == 200, login.text
        access_token = login.json().get("access_token") or confirm.json().get("access_token")
        assert access_token
        hdr = {"Authorization": f"Bearer {access_token}"}

        # 4. Accept the current developer terms.
        assert client.post("/v1/platform/terms/accept", headers=hdr,
                           json={"document_type": "api_terms", "document_version": tv}).status_code == 200

        # 5. Automatic TEST enrollment on control-plane access (no manual review).
        assert client.get("/v1/platform/developer/overview", headers=hdr).status_code == 200

        # 6-8. Project -> service account -> agro_test_ key.
        proj = client.post("/v1/platform/developer/projects", headers=hdr, json={"name": "front-door", "environment": "test"})
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["project"]["id"]
        scopes = ["projects:read", "fields:read"]
        sa = client.post(f"/v1/platform/developer/projects/{project_id}/service-accounts", headers=hdr,
                         json={"name": "agent", "scopes": scopes})
        assert sa.status_code == 201, sa.text
        key = client.post(f"/v1/platform/developer/service-accounts/{sa.json()['service_account']['id']}/keys",
                          headers=hdr, json={"name": "primary", "scopes": scopes})
        assert key.status_code == 201, key.text
        plaintext = key.json()["plaintext_key"]
        assert plaintext.startswith("agro_test_")

        # 9. First successful Platform API request with the new key.
        me = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}"})
        assert me.status_code == 200, me.text
        assert me.json()["principal"]["environment"] == "test"

        # No manual AGRO-AI review event occurred anywhere in the journey.
        db = Session()
        try:
            enrollment = db.query(PlatformProgramEnrollment).filter_by(organization_id=org_id).one()
            assert enrollment.program == "developer_self_service"
            assert enrollment.approved_by_user_id is None  # automatic, no human approver
            manual_reviews = (
                db.query(PlatformProductAuditEvent)
                .filter(PlatformProductAuditEvent.organization_id == org_id,
                        PlatformProductAuditEvent.event_type.like("%application%review%"))
                .count()
            )
            assert manual_reviews == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)

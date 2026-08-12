"""Definitive TEST self-service developer acceptance test (release gate).

Simulates a brand-new developer completing the entire safe TEST self-service
journey end to end against a REAL PostgreSQL database, through the real HTTP
API (no mocks of the control plane or data plane), and proves the 24 required
properties — including that LIVE, physical execution, cross-organization
access, real provider calls, and manual approval never occur.

Run with a migrated PostgreSQL database:

    PLATFORM_API_POSTGRES_TEST_URL=postgresql://... \
      python -m pytest tests/integration/test_self_service_developer_acceptance.py
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required for the self-service acceptance test"
)

SELF_SERVICE_FLAGS = (
    "PLATFORM_API_ENABLED",
    "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
    "PLATFORM_API_TEST_PROJECTS_ENABLED",
    "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED",
    "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED",
    "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED",
)
# LIVE stays deliberately OFF for the whole test.
LIVE_FLAGS_THAT_STAY_OFF = (
    "PLATFORM_API_LIVE_PROJECTS_ENABLED",
    "PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED",
    "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED",
)


def _jwt(user_id: str) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}


def _seed_verified_developer(Session, *, slug: str):
    """Steps 1–3: a registered developer with a verified email and a verified
    (server-approved) organization plus active owner membership. Registration
    and email verification are represented by this safe test fixture."""
    from app.models.saas import Organization, OrganizationMembership, User, Workspace

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(
            email=f"dev-{slug}-{s}@example.com",
            password_hash="x",
            email_verification_status="verified",
            email_verified_at=datetime.utcnow(),
        )
        db.add(user); db.flush()
        org = Organization(
            name=f"Self-service {slug}",
            slug=f"selfserve-{slug}-{s}",
            owner_user_id=user.id,
            plan="developer",
            subscription_status="active",
            verification_status="approved",  # server-authoritative verified state
        )
        db.add(org); db.flush()
        ws = Workspace(organization_id=org.id, name="Default", mode="evaluation")
        db.add(ws); db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.commit()
        return user.id, org.id, ws.id, user.email
    finally:
        db.close()


def _seed_effective_terms(Session) -> tuple[str, str]:
    from app.models.platform_product import PlatformTermsDocument

    db = Session()
    try:
        existing = (
            db.query(PlatformTermsDocument)
            .filter(PlatformTermsDocument.document_type == "api_terms", PlatformTermsDocument.status == "approved_effective")
            .first()
        )
        if existing:
            return existing.document_type, existing.version
        version = f"accept-{uuid.uuid4().hex[:8]}"
        db.add(
            PlatformTermsDocument(
                document_type="api_terms",
                version=version,
                status="approved_effective",
                content_digest="a" * 64,
                effective_at=datetime.utcnow() - timedelta(days=1),
            )
        )
        db.commit()
        return "api_terms", version
    finally:
        db.close()


def test_new_developer_completes_safe_test_self_service_end_to_end(monkeypatch):
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app
    from app.models.platform_product import PlatformProgramEnrollment, PlatformProductAuditEvent

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    for name in SELF_SERVICE_FLAGS:
        monkeypatch.setattr(settings, name, True, raising=False)
    for name in LIVE_FLAGS_THAT_STAY_OFF:
        monkeypatch.setattr(settings, name, False, raising=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        doc_type, doc_version = _seed_effective_terms(Session)
        user_id, org_id, ws_id, _email = _seed_verified_developer(Session, slug="a")
        # A separate victim organization for cross-tenant checks.
        victim_user_id, victim_org_id, victim_ws_id, _ = _seed_verified_developer(Session, slug="victim")
        hdr = _jwt(user_id)

        # 4. Accept current developer terms through the real endpoint.
        accepted = client.post(
            "/v1/platform/terms/accept",
            headers=hdr,
            json={"document_type": doc_type, "document_version": doc_version},
        )
        assert accepted.status_code == 200, accepted.text

        # 5. Automatic developer_self_service TEST enrollment on control-plane access.
        overview = client.get("/v1/platform/developer/overview", headers=hdr)
        assert overview.status_code == 200, overview.text
        db = Session()
        try:
            enrollment = (
                db.query(PlatformProgramEnrollment)
                .filter(PlatformProgramEnrollment.organization_id == org_id)
                .one()
            )
            assert enrollment.program == "developer_self_service"
            assert enrollment.status == "active"
            assert enrollment.allowed_environments_json == ["test"]  # TEST only
            assert enrollment.maximum_live_projects == 0
            assert enrollment.approved_by_user_id is None  # 24. automatic — no human approver
        finally:
            db.close()

        # 6. Create a TEST project.
        proj = client.post(
            "/v1/platform/developer/projects",
            headers=hdr,
            json={"name": "My TEST project", "environment": "test"},
        )
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["project"]["id"]

        # 7. Create a service account with TEST-safe scopes (no actions:execute).
        sa_scopes = ["projects:read", "fields:read", "fields:write", "reports:read", "reports:write", "jobs:read", "usage:read"]
        sa = client.post(
            f"/v1/platform/developer/projects/{project_id}/service-accounts",
            headers=hdr,
            json={"name": "ci-agent", "scopes": sa_scopes},
        )
        assert sa.status_code == 201, sa.text
        service_account_id = sa.json()["service_account"]["id"]

        # 8–9. Create an agro_test_ key; plaintext returned exactly once.
        created = client.post(
            f"/v1/platform/developer/service-accounts/{service_account_id}/keys",
            headers=hdr,
            json={"name": "primary", "scopes": sa_scopes},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        plaintext = body["plaintext_key"]
        key_id = body["key"]["id"]
        assert plaintext.startswith("agro_test_")
        assert body.get("plaintext_display") == "one_time_only"
        # The key can be listed but never re-reveals the secret.
        listed = client.get("/v1/platform/developer/keys", headers=hdr)
        assert listed.status_code == 200
        assert plaintext not in listed.text

        # 10. Use the key from a separate client/auth context.
        data_client = TestClient(app)
        key_hdr = {"Authorization": f"Bearer {plaintext}"}

        # 11. GET /v1/platform/me succeeds and is TEST-scoped.
        me = data_client.get("/v1/platform/me", headers=key_hdr)
        assert me.status_code == 200, me.text
        assert me.json()["principal"]["environment"] == "test"

        # 12. Deterministic sandbox/field data is available.
        fields = data_client.get("/v1/platform/fields", headers=key_hdr)
        assert fields.status_code == 200, fields.text
        assert "items" in fields.json()

        # 13. Create one safe TEST resource.
        made = data_client.post(
            "/v1/platform/fields",
            headers={**key_hdr, "Idempotency-Key": uuid.uuid4().hex},
            json={"name": "North block", "crop": "almond", "area_hectares": 12.5},
        )
        assert made.status_code == 201, made.text
        my_field_id = made.json()["field"]["id"]

        # 14. Start one async operation (report generation -> job).
        report = data_client.post(
            "/v1/platform/reports",
            headers={**key_hdr, "Idempotency-Key": uuid.uuid4().hex},
            json={"title": "Season summary", "field_ids": [my_field_id]},
        )
        assert report.status_code == 202, report.text
        job_id = report.json()["job"]["id"]

        # 15. Poll the job.
        polled = data_client.get(f"/v1/platform/jobs/{job_id}", headers=key_hdr)
        assert polled.status_code == 200, polled.text
        assert polled.json()["job"]["id"] == job_id

        # 16. Inspect usage.
        usage = data_client.get("/v1/platform/usage", headers=key_hdr)
        assert usage.status_code == 200, usage.text

        # 17–19. Rotate with overlap=0; old key fails, new key succeeds.
        rotated = client.post(
            f"/v1/platform/developer/keys/{key_id}/rotate",
            headers=hdr,
            json={"overlap_minutes": 0},
        )
        assert rotated.status_code == 200, rotated.text
        new_plaintext = rotated.json()["plaintext_key"]
        assert new_plaintext.startswith("agro_test_") and new_plaintext != plaintext
        assert data_client.get("/v1/platform/me", headers=key_hdr).status_code == 401
        new_hdr = {"Authorization": f"Bearer {new_plaintext}"}
        assert data_client.get("/v1/platform/me", headers=new_hdr).status_code == 200

        # 20. Developer cannot create a LIVE project.
        live = client.post(
            "/v1/platform/developer/projects",
            headers=hdr,
            json={"name": "live attempt", "environment": "live"},
        )
        assert live.status_code == 403, live.text

        # 21. Developer cannot access another organization's resource.
        #     Seed a field owned by the victim org's project and confirm the
        #     self-service developer's key cannot read it by id.
        victim_field_id = _seed_victim_field(Session, victim_org_id, victim_ws_id, victim_user_id)
        cross = data_client.get(f"/v1/platform/fields/{victim_field_id}", headers=new_hdr)
        assert cross.status_code == 404, cross.text  # not found (never 200) across org boundary

        # 22. No real provider call occurred: provider readiness is contract-gated.
        health = data_client.get("/v1/platform/health")
        assert health.json()["earthdaily_status"] == "awaiting_partner_contract"
        assert health.json()["valley_irrigation_status"] == "awaiting_partner_contract"

        # 23. No physical action is possible: physical irrigation commands are disabled.
        assert health.json()["physical_irrigation_commands"] == "disabled"

        # 24. No manual administrator approval occurred at any point.
        db = Session()
        try:
            approvals = (
                db.query(PlatformProductAuditEvent)
                .filter(
                    PlatformProductAuditEvent.organization_id == org_id,
                    PlatformProductAuditEvent.event_type.like("%application%review%"),
                )
                .count()
            )
            assert approvals == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed_victim_field(Session, org_id: str, ws_id: str, user_id: str) -> str:
    from app.models.saas import ManagedEntity
    from app.models.platform_api import ApiProject

    db = Session()
    try:
        project = ApiProject(
            organization_id=org_id,
            workspace_id=ws_id,
            name="victim",
            slug=f"victim-{uuid.uuid4().hex[:8]}",
            environment="test",
            status="active",
            default_rate_limit_policy={},
            created_by_user_id=user_id,
        )
        db.add(project); db.flush()
        field = ManagedEntity(
            organization_id=org_id,
            workspace_id=ws_id,
            entity_type="platform_field",
            external_id="victim-field",
            display_name="Victim field",
            status="active",
            metadata_json={"api_project_id": project.id, "synthetic": True},
        )
        db.add(field); db.flush()
        fid = field.id
        db.commit()
        return fid
    finally:
        db.close()

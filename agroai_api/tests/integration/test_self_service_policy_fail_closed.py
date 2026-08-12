"""TEST self-service policy fails closed (real PG): enrollment suspension
invalidates keys, and accepted CURRENT terms are a hard auto-enrollment
prerequisite — neither depends on unrelated private-beta/partner flags."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")

# Everything that could *accidentally* enforce policy stays OFF; only the
# self-service auto-enroll flag is ON.
OFF_FLAGS = ("PLATFORM_API_PRIVATE_BETA_ENABLED", "PLATFORM_API_PARTNER_PROGRAM_ENABLED",
             "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED")


def _client(app, Session):
    from app.db.base import get_db

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_suspending_self_service_enrollment_fails_the_key_without_private_beta_flags(monkeypatch):
    from app.core.config import settings
    from app.main import app
    from app.models.saas import Organization, OrganizationMembership, User, Workspace
    from app.models.platform_api import ApiProject, ApiServiceAccount
    from app.models.platform_product import PlatformProgramEnrollment
    from app.platform_api.keys import create_platform_key

    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", True, raising=False)
    for name in OFF_FLAGS:
        monkeypatch.setattr(settings, name, False, raising=False)

    Session = sessionmaker(bind=create_engine(POSTGRES_URL, pool_pre_ping=True), expire_on_commit=False)
    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"susp-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        org = Organization(name=f"Susp {s}", slug=f"susp-{s}", owner_user_id=user.id,
                           plan="developer", subscription_status="active", verification_status="approved")
        db.add(org); db.flush()
        ws = Workspace(organization_id=org.id, name="w", mode="evaluation"); db.add(ws); db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        enrollment = PlatformProgramEnrollment(
            organization_id=org.id, program="developer_self_service", status="active",
            approved_at=datetime.utcnow(), allowed_environments_json=["test"],
            maximum_projects=5, maximum_service_accounts=5, maximum_keys=10, effective_at=datetime.utcnow())
        db.add(enrollment); db.flush()
        project = ApiProject(organization_id=org.id, workspace_id=ws.id, name="p", slug=f"p-{s}",
                             environment="test", status="active", default_rate_limit_policy={}, created_by_user_id=user.id)
        db.add(project); db.flush()
        sa = ApiServiceAccount(organization_id=org.id, api_project_id=project.id, workspace_id=ws.id,
                               name="sa", status="active", scopes=["projects:read"], created_by_user_id=user.id)
        db.add(sa); db.flush()
        _key, plaintext = create_platform_key(db, project=project, service_account=sa, name="k",
                                              scopes=["projects:read"], created_by_user_id=user.id, workspace_id=ws.id)
        db.commit()
        enrollment_id = enrollment.id
    finally:
        db.close()

    client = _client(app, Session)
    try:
        hdr = {"Authorization": f"Bearer {plaintext}"}
        assert client.get("/v1/platform/me", headers=hdr).status_code == 200  # works while enrolled

        db = Session()
        try:
            db.get(PlatformProgramEnrollment, enrollment_id).status = "suspended"
            db.commit()
        finally:
            db.close()

        # Next request fails closed even though private-beta/partner/sandbox are all OFF.
        denied = client.get("/v1/platform/me", headers=hdr)
        assert denied.status_code == 403, denied.text
        assert denied.json().get("code") == "platform_api_entitlement_inactive"
    finally:
        app.dependency_overrides.pop("_", None)
        from app.db.base import get_db
        app.dependency_overrides.pop(get_db, None)


def _seed_dev(Session):
    from app.models.saas import Organization, OrganizationMembership, User, Workspace

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"terms-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        org = Organization(name=f"Terms {s}", slug=f"terms-{s}", owner_user_id=user.id,
                           plan="developer", subscription_status="active", verification_status="approved")
        db.add(org); db.flush()
        db.add(Workspace(organization_id=org.id, name="w", mode="evaluation"))
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.commit()
        return user.id, org.id
    finally:
        db.close()


def _publish_terms(Session, *, version, effective_days_ago=1):
    from app.models.platform_product import PlatformTermsDocument
    db = Session()
    try:
        db.add(PlatformTermsDocument(document_type="api_terms", version=version, status="approved_effective",
                                     content_digest="a" * 64, effective_at=datetime.utcnow() - timedelta(days=effective_days_ago)))
        db.commit()
    finally:
        db.close()


def _has_enrollment(Session, org_id):
    from app.models.platform_product import PlatformProgramEnrollment
    db = Session()
    try:
        return db.query(PlatformProgramEnrollment).filter_by(organization_id=org_id).count() > 0
    finally:
        db.close()


def test_auto_enroll_requires_accepted_current_terms(monkeypatch):
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.main import app

    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
                 "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)
    # Deliberately leave TERMS_ENFORCEMENT OFF: terms must still be enforced.
    monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False, raising=False)

    Session = sessionmaker(bind=create_engine(POSTGRES_URL, pool_pre_ping=True), expire_on_commit=False)
    client = _client(app, Session)
    try:
        user_id, org_id = _seed_dev(Session)
        _publish_terms(Session, version=f"v1-{uuid.uuid4().hex[:6]}")
        hdr = {"Authorization": f"Bearer {create_access_token({'sub': user_id, 'org_id': org_id, 'tenant_id': org_id, 'role': 'owner'})}"}

        # 1. Current terms unaccepted -> no auto-enrollment.
        r1 = client.get("/v1/platform/developer/overview", headers=hdr)
        assert r1.status_code in (401, 403), r1.text
        assert not _has_enrollment(Session, org_id)

        # 2. Accept the current terms -> auto-enrollment succeeds.
        from app.platform_api.terms import required_documents
        db = Session()
        try:
            doc = required_documents(db)[0]
            doc_type, doc_version = doc.document_type, doc.version
        finally:
            db.close()
        # temporarily allow the accept endpoint (guarded by TERMS_ENFORCEMENT flag)
        monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", True, raising=False)
        assert client.post("/v1/platform/terms/accept", headers=hdr,
                           json={"document_type": doc_type, "document_version": doc_version}).status_code == 200
        assert client.get("/v1/platform/developer/overview", headers=hdr).status_code == 200
        assert _has_enrollment(Session, org_id)
    finally:
        from app.db.base import get_db
        app.dependency_overrides.pop(get_db, None)


def test_auto_enroll_rejects_superseded_terms_only(monkeypatch):
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.main import app

    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
                 "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)

    Session = sessionmaker(bind=create_engine(POSTGRES_URL, pool_pre_ping=True), expire_on_commit=False)
    client = _client(app, Session)
    try:
        user_id, org_id = _seed_dev(Session)
        v1 = f"v1-{uuid.uuid4().hex[:6]}"
        _publish_terms(Session, version=v1, effective_days_ago=5)
        hdr = {"Authorization": f"Bearer {create_access_token({'sub': user_id, 'org_id': org_id, 'tenant_id': org_id, 'role': 'owner'})}"}
        assert client.post("/v1/platform/terms/accept", headers=hdr,
                           json={"document_type": "api_terms", "document_version": v1}).status_code == 200

        # A newer effective version supersedes v1 as the current required doc.
        v2 = f"v2-{uuid.uuid4().hex[:6]}"
        _publish_terms(Session, version=v2, effective_days_ago=1)

        # The developer has accepted only the OLD version -> no auto-enrollment.
        r = client.get("/v1/platform/developer/overview", headers=hdr)
        assert r.status_code in (401, 403), r.text
        assert not _has_enrollment(Session, org_id)
    finally:
        from app.db.base import get_db
        app.dependency_overrides.pop(get_db, None)

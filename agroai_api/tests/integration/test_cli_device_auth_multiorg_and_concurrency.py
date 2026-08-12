"""Multi-organization CLI device binding + atomic single-winner token mint (real PG)."""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")


def _engine():
    return create_engine(POSTGRES_URL, pool_pre_ping=True)


def _seed_user_in_two_orgs(Session):
    """User U owns Org A (created first) and Org B (created second); both approved
    and self-service enrolled."""
    from app.models.saas import Organization, OrganizationMembership, User, Workspace
    from app.models.platform_product import PlatformProgramEnrollment

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"multi-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        orgs = {}
        for label in ("A", "B"):
            org = Organization(name=f"Org {label} {s}", slug=f"org-{label.lower()}-{s}", owner_user_id=user.id,
                               plan="developer", subscription_status="active", verification_status="approved")
            db.add(org); db.flush()
            db.add(Workspace(organization_id=org.id, name="w", mode="evaluation"))
            db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
            db.add(PlatformProgramEnrollment(
                organization_id=org.id, program="developer_self_service", status="active",
                approved_at=datetime.utcnow(), allowed_environments_json=["test"],
                maximum_projects=5, maximum_service_accounts=5, maximum_keys=10, effective_at=datetime.utcnow(),
            ))
            orgs[label] = org.id
        db.commit()
        return user.id, orgs["A"], orgs["B"]
    finally:
        db.close()


def test_cli_device_token_is_bound_to_the_approved_organization(monkeypatch):
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.db.base import get_db
    from app.main import app
    from app.models.platform_api import ApiProject
    from app.models.saas import OrganizationMembership

    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
                 "PLATFORM_API_TEST_PROJECTS_ENABLED", "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)

    Session = sessionmaker(bind=_engine(), expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        user_id, org_a, org_b = _seed_user_in_two_orgs(Session)
        # A browser session scoped to Org B (the SECOND / non-default org).
        browser_b = {"Authorization": f"Bearer {create_access_token({'sub': user_id, 'org_id': org_b, 'tenant_id': org_b, 'role': 'owner'})}"}

        auth = client.post("/v1/platform/cli/device/authorization", json={}).json()
        approved = client.post("/v1/platform/cli/device/approve", headers=browser_b, json={"user_code": auth["user_code"]})
        assert approved.status_code == 200, approved.text

        token_resp = client.post("/v1/platform/cli/device/token", json={"device_code": auth["device_code"]})
        assert token_resp.status_code == 200
        assert token_resp.json()["organization_id"] == org_b
        cli = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}

        # The CLI session resolves Org B, not the user's first org (A).
        assert client.get("/v1/platform/developer/overview", headers=cli).status_code == 200
        created = client.post("/v1/platform/developer/projects", headers=cli, json={"name": "b-proj", "environment": "test"})
        assert created.status_code == 201, created.text
        project_id = created.json()["project"]["id"]
        db = Session()
        try:
            assert db.get(ApiProject, project_id).organization_id == org_b  # bound to B
        finally:
            db.close()

        # A project owned by Org A is not reachable through the Org B CLI session,
        # and there is no request field that can switch the session into Org A.
        a_project = ApiProject(organization_id=org_a, name="a-proj", slug=f"a-{uuid.uuid4().hex[:6]}",
                               environment="test", status="active", default_rate_limit_policy={}, created_by_user_id=user_id)
        db = Session()
        try:
            db.add(a_project); db.commit(); a_project_id = a_project.id
        finally:
            db.close()
        assert client.get(f"/v1/platform/developer/projects/{a_project_id}", headers=cli).status_code == 404
        # Attempts to smuggle Org A via header/query/body do not switch the session.
        assert client.get(f"/v1/platform/developer/projects/{a_project_id}", headers={**cli, "X-Organization-Id": org_a}).status_code == 404
        assert client.get(f"/v1/platform/developer/projects/{a_project_id}?organization_id={org_a}", headers=cli).status_code == 404

        # Removing the user's Org B membership immediately invalidates the CLI session.
        db = Session()
        try:
            m = db.query(OrganizationMembership).filter_by(organization_id=org_b, user_id=user_id).first()
            m.status = "inactive"
            db.commit()
        finally:
            db.close()
        assert client.get("/v1/platform/developer/overview", headers=cli).status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _approved_challenge(Session, user_id, org_id):
    from app.platform_api.device_auth import create_device_authorization, approve_device_authorization

    db = Session()
    try:
        device_code, row = create_device_authorization(db)
        approve_device_authorization(db, user_code=row.user_code, organization_id=org_id, approved_by_user_id=user_id)
        return device_code
    finally:
        db.close()


def test_concurrent_token_exchange_has_exactly_one_winner(monkeypatch):
    from app.platform_api.device_auth import exchange_device_token
    from app.models.platform_product import PlatformCliDeviceAuthorization

    Session = sessionmaker(bind=_engine(), expire_on_commit=False)
    user_id, org_a, org_b = _seed_user_in_two_orgs(Session)
    device_code = _approved_challenge(Session, user_id, org_b)

    def _exchange(_i):
        db = Session()  # independent session per concurrent request
        try:
            return exchange_device_token(db, device_code=device_code)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(_exchange, range(12)))

    tokens = [r for r in results if "access_token" in r]
    rejected = [r for r in results if r.get("error") == "invalid_grant"]
    assert len(tokens) == 1, f"expected exactly one minted token, got {len(tokens)}"
    assert len(rejected) == len(results) - 1, f"all other exchanges must be rejected: {results}"
    # The minted token is bound to the approved organization.
    assert tokens[0]["organization_id"] == org_b

    # Exactly one consumed transition persisted.
    db = Session()
    try:
        row = db.query(PlatformCliDeviceAuthorization).filter_by(device_code_hash=__import__("app.platform_api.device_auth", fromlist=["_hash_device_code"])._hash_device_code(device_code)).one()
        assert row.status == "consumed" and row.consumed_at is not None
    finally:
        db.close()


def test_cli_logout_revokes_the_session_server_side(monkeypatch):
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app

    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
                 "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)
    Session = sessionmaker(bind=_engine(), expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        from app.core.security import create_access_token
        user_id, org_a, org_b = _seed_user_in_two_orgs(Session)
        browser_b = {"Authorization": f"Bearer {create_access_token({'sub': user_id, 'org_id': org_b, 'tenant_id': org_b, 'role': 'owner'})}"}
        auth = client.post("/v1/platform/cli/device/authorization", json={}).json()
        client.post("/v1/platform/cli/device/approve", headers=browser_b, json={"user_code": auth["user_code"]})
        cli_token = client.post("/v1/platform/cli/device/token", json={"device_code": auth["device_code"]}).json()["access_token"]
        cli = {"Authorization": f"Bearer {cli_token}"}

        # Works before logout.
        assert client.get("/v1/platform/developer/overview", headers=cli).status_code == 200

        # Server-side logout revokes the session.
        out = client.post("/v1/platform/cli/device/logout", headers=cli)
        assert out.status_code == 200 and out.json()["status"] == "revoked"

        # The same token now fails immediately on any authenticated route.
        assert client.get("/v1/platform/developer/overview", headers=cli).status_code == 401
        # An already-revoked token cannot even re-invoke logout.
        assert client.post("/v1/platform/cli/device/logout", headers=cli).status_code == 401

        # An unknown/deleted CLI session id fails closed too.
        forged = {"Authorization": f"Bearer {create_access_token({'sub': user_id, 'org_id': org_b, 'tenant_id': org_b, 'cli_session': 'does-not-exist'})}"}
        assert client.get("/v1/platform/developer/overview", headers=forged).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_device_authorization_is_rate_limited_per_ip(monkeypatch):
    from app.core.config import settings
    from app.core.rate_limiting import limiter
    from app.db.base import get_db
    from app.main import app

    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", True, raising=False)
    # Reuse the authoritative IP limiter; lower the bound for a deterministic test.
    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTHZ_RATE_LIMIT", "3/minute", raising=False)
    limiter.reset()
    Session = sessionmaker(bind=_engine(), expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        codes = [client.post("/v1/platform/cli/device/authorization", json={}).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200], codes
        assert 429 in codes[3:], f"anonymous device authorization must be rate limited: {codes}"
    finally:
        limiter.reset()
        app.dependency_overrides.pop(get_db, None)

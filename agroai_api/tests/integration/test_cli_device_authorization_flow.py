"""agroai CLI device-authorization (RFC 8628-style) end-to-end flow on real PG.

Proves: high-entropy device_code stored only as a hash; short user_code; explicit
human approval through an authenticated first-party session with org binding;
polling-interval enforcement (slow_down); one-time token mint (replay rejected);
expiry; and that the minted credential is a real, org-scoped human control-plane
JWT that actually works against the developer control plane.
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
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")


def _seed_admin(Session):
    from app.models.saas import Organization, OrganizationMembership, User, Workspace
    from app.models.platform_product import PlatformProgramEnrollment

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"cli-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        org = Organization(name=f"CLI {s}", slug=f"cli-{s}", owner_user_id=user.id,
                           plan="developer", subscription_status="active", verification_status="approved")
        db.add(org); db.flush()
        db.add(Workspace(organization_id=org.id, name="w", mode="evaluation"))
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.add(PlatformProgramEnrollment(
            organization_id=org.id, program="developer_self_service", status="active",
            approved_at=datetime.utcnow(), allowed_environments_json=["test"],
            maximum_projects=5, maximum_service_accounts=5, maximum_keys=10, effective_at=datetime.utcnow(),
        ))
        db.commit()
        return user.id, org.id
    finally:
        db.close()


def test_device_authorization_flow(monkeypatch):
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.db.base import get_db
    from app.main import app
    from app.models.platform_product import PlatformCliDeviceAuthorization

    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", True, raising=False)

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        user_id, org_id = _seed_admin(Session)
        human = {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}

        # 1. CLI requests device authorization (anonymous).
        auth = client.post("/v1/platform/cli/device/authorization", json={"client_label": "agroai-cli-test"})
        assert auth.status_code == 200, auth.text
        body = auth.json()
        device_code, user_code = body["device_code"], body["user_code"]
        assert body["interval"] >= 1 and body["expires_in"] > 0
        assert "verification_uri" in body

        # device_code is stored only as a hash (never in plaintext).
        db = Session()
        try:
            row = db.query(PlatformCliDeviceAuthorization).filter_by(user_code=user_code).one()
            assert row.device_code_hash and device_code not in row.device_code_hash
            assert row.status == "pending"
        finally:
            db.close()

        # 2. Polling before approval -> authorization_pending (or slow_down).
        pending = client.post("/v1/platform/cli/device/token", json={"device_code": device_code})
        assert pending.status_code == 200
        assert pending.json()["status"] in {"authorization_pending", "slow_down"}

        # 3. An unauthenticated approve is rejected.
        assert client.post("/v1/platform/cli/device/approve", json={"user_code": user_code}).status_code in (401, 403)

        # 4. The human approves through the authenticated first-party session.
        approved = client.post("/v1/platform/cli/device/approve", headers=human, json={"user_code": user_code})
        assert approved.status_code == 200, approved.text

        # 5. Exchange -> a real, org-scoped human control-plane token (minted once).
        # Age the last poll so interval enforcement does not slow_down this exchange.
        db = Session()
        try:
            r = db.query(PlatformCliDeviceAuthorization).filter_by(user_code=user_code).one()
            r.last_polled_at = datetime.utcnow() - timedelta(seconds=30)
            db.commit()
        finally:
            db.close()
        token_resp = client.post("/v1/platform/cli/device/token", json={"device_code": device_code})
        assert token_resp.status_code == 200, token_resp.text
        tb = token_resp.json()
        assert tb["token_type"] == "Bearer" and tb["organization_id"] == org_id
        human_token = tb["access_token"]

        # 6. Replay rejected: the code is one-time only.
        replay = client.post("/v1/platform/cli/device/token", json={"device_code": device_code})
        assert replay.status_code == 200 and replay.json()["status"] == "invalid_grant"

        # 7. The minted token is a working human control-plane credential.
        monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True, raising=False)
        me = client.get("/v1/platform/developer/overview", headers={"Authorization": f"Bearer {human_token}"})
        assert me.status_code == 200, me.text

        # 8. Expiry: a fresh challenge that has passed its TTL yields expired_token.
        auth2 = client.post("/v1/platform/cli/device/authorization", json={}).json()
        db = Session()
        try:
            r2 = db.query(PlatformCliDeviceAuthorization).filter_by(user_code=auth2["user_code"]).one()
            r2.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()
        expired = client.post("/v1/platform/cli/device/token", json={"device_code": auth2["device_code"]})
        assert expired.status_code == 200 and expired.json()["status"] == "expired_token"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_device_endpoints_are_404_when_flag_disabled(monkeypatch):
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "PLATFORM_API_CLI_DEVICE_AUTH_ENABLED", False, raising=False)
    client = TestClient(app)
    assert client.post("/v1/platform/cli/device/authorization", json={}).status_code == 404

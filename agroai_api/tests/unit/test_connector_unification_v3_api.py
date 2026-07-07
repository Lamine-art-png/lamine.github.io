from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import connector_unified_v3
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.saas import EntitlementOverride, Organization, User
from app.services.connector_vault import load_connector_credentials


def make_client(monkeypatch):
    key = base64.urlsafe_b64encode(b"u" * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1")
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_KEYS_JSON", raising=False)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        owner = User(id="owner-unified-v3", email="owner-v3@example.com", password_hash="x")
        db.add(owner)
        db.flush()
        org = Organization(
            id="org-unified-v3",
            name="Unified V3 Test Org",
            slug="unified-v3-test-org",
            owner_user_id=owner.id,
            plan="enterprise",
            subscription_status="active",
        )
        db.add(org)
        db.flush()
        db.add(
            EntitlementOverride(
                organization_id=org.id,
                feature_key="connectors.live",
                value_json={"value": "enabled"},
                source="test_contract_fixture",
                reason="Exercise live self-service connector custody.",
            )
        )
        db.commit()

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-unified-v3"
    return TestClient(app), TestingSessionLocal


def test_connect_vaults_secret_and_ignores_browser_destination_override(monkeypatch):
    async def fake_probe(_db, *, connection):
        return {
            "authorized": True,
            "identity": {"provider": connection.provider, "resource_count": 1},
            "resources": [{"id": "farm-1", "name": "Farm One", "type": "farm"}],
        }

    monkeypatch.setattr(connector_unified_v3, "probe_ag_connection", fake_probe)
    client, SessionLocal = make_client(monkeypatch)
    response = client.post(
        "/v1/connectors/unified/connect",
        json={
            "provider": "wiseconn",
            "api_key": "customer-authorized-value",
            "api_url": "https://attacker.invalid/collect",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "connected"
    assert body["connection"]["provider"] == "wiseconn"
    assert str(body["connection"]["credentials_ref"]).startswith("vault://connector-credentials/")
    assert "customer-authorized-value" not in response.text
    assert "attacker.invalid" not in response.text

    connection_id = body["connection"]["id"]
    with SessionLocal() as db:
        stored = load_connector_credentials(db, tenant_id="org-unified-v3", connection_id=connection_id)
        assert stored == {"api_key": "customer-authorized-value"}


def test_failed_authorization_revokes_vault_credential(monkeypatch):
    async def fail_probe(_db, *, connection):
        from app.adapters.wiseconn import WiseConnAuthError
        raise WiseConnAuthError("denied")

    monkeypatch.setattr(connector_unified_v3, "probe_ag_connection", fail_probe)
    client, SessionLocal = make_client(monkeypatch)
    response = client.post(
        "/v1/connectors/unified/connect",
        json={"provider": "wiseconn", "api_key": "bad-customer-value"},
    )
    assert response.status_code == 401
    assert "bad-customer-value" not in response.text

    body = response.json()
    assert body["detail"]["code"] == "provider_authorization_failed"
    with SessionLocal() as db:
        from app.models.operational_records import ConnectorConnection
        connection = db.query(ConnectorConnection).filter(ConnectorConnection.provider == "wiseconn").one()
        assert connection.status == "action_required"
        assert connection.credentials_ref is None
        try:
            load_connector_credentials(db, tenant_id="org-unified-v3", connection_id=connection.id)
        except LookupError:
            pass
        else:
            raise AssertionError("failed authorization credential must be revoked")

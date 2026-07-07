from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, User
from app.services.connector_vault import load_connector_credentials


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        owner = User(id="owner-ag-test", email="ag-owner@example.com", password_hash="x")
        db.add(owner)
        db.flush()
        db.add(
            Organization(
                id="org-ag-test",
                name="Unified Ag Connector Test Org",
                slug="unified-ag-connector-test-org",
                owner_user_id=owner.id,
                plan="enterprise",
                subscription_status="active",
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
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-ag-test"
    return TestClient(app), TestingSessionLocal


def test_unified_wiseconn_connect_vaults_secret_and_discovers(monkeypatch):
    key = base64.urlsafe_b64encode(b"w" * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1")

    async def fake_probe(_db, *, connection):
        assert connection.provider == "wiseconn"
        return {
            "authorized": True,
            "identity": {"provider": "wiseconn", "resource_count": 1},
            "resources": [{"id": "farm-1", "name": "North Ranch", "type": "farm"}],
        }

    monkeypatch.setattr("app.api.v1.ag_connector_lifecycle.probe_ag_connection", fake_probe)
    client, SessionLocal = make_client()
    response = client.post(
        "/v1/connectors/unified/connect",
        json={"provider": "wiseconn", "access_value": "customer-wiseconn-token", "workspace_id": "workspace-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "connected"
    assert body["count"] == 1
    assert str(body["connection"]["credentials_ref"]).startswith("vault://connector-credentials/")
    assert "customer-wiseconn-token" not in str(body)

    with SessionLocal() as db:
        row = db.query(ConnectorConnection).filter(ConnectorConnection.provider == "wiseconn").one()
        stored = load_connector_credentials(db, tenant_id="org-ag-test", connection_id=row.id)
        assert stored["api_key"] == "customer-wiseconn-token"
        assert "customer-wiseconn-token" not in str(row.config_json)


def test_unified_invalid_talgil_credential_never_fake_connects(monkeypatch):
    from app.adapters.talgil import TalgilAuthError

    key = base64.urlsafe_b64encode(b"t" * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1")

    async def fake_probe(_db, *, connection):
        raise TalgilAuthError("bad test credential")

    monkeypatch.setattr("app.api.v1.ag_connector_lifecycle.probe_ag_connection", fake_probe)
    client, SessionLocal = make_client()
    response = client.post(
        "/v1/connectors/unified/connect",
        json={"provider": "talgil", "access_value": "bad-talgil-token"},
    )
    assert response.status_code == 401
    with SessionLocal() as db:
        row = db.query(ConnectorConnection).filter(ConnectorConnection.provider == "talgil").one()
        assert row.status == "action_required"
        assert row.credentials_ref is None


def test_unified_openet_selection_saves_scope_without_secret(monkeypatch):
    key = base64.urlsafe_b64encode(b"o" * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1")

    async def fake_probe(_db, *, connection):
        return {"authorized": True, "identity": {"provider": "openet"}, "resources": []}

    monkeypatch.setattr("app.api.v1.ag_connector_lifecycle.probe_ag_connection", fake_probe)
    client, SessionLocal = make_client()
    response = client.post(
        "/v1/connectors/unified/connect",
        json={"provider": "openet", "access_value": "customer-openet-key"},
    )
    assert response.status_code == 200, response.text
    connection_id = response.json()["connection"]["id"]

    selection = client.post(
        f"/v1/connectors/unified/{connection_id}/selection",
        json={"scope_mode": "openet_field_ids", "field_ids": ["et-field-1", "et-field-2"]},
    )
    assert selection.status_code == 200, selection.text
    assert selection.json()["selected_resource_ids"] == ["et-field-1", "et-field-2"]

    with SessionLocal() as db:
        row = db.get(ConnectorConnection, connection_id)
        assert row is not None
        assert row.config_json["field_ids"] == ["et-field-1", "et-field-2"]
        assert "customer-openet-key" not in str(row.config_json)

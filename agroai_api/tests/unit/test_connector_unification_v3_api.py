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


def install_success_probe(monkeypatch, provider="wiseconn", resources=None):
    async def fake_probe(actual_provider, api_key):
        assert actual_provider == provider
        assert api_key
        return {
            "identity": {"provider": actual_provider, "resource_count": len(resources or [])},
            "resources": resources or [],
        }
    monkeypatch.setattr(connector_unified_v3, "_probe_candidate", fake_probe)


def test_connect_vaults_secret_and_ignores_browser_destination_override(monkeypatch):
    async def fake_probe(provider, api_key):
        assert provider == "wiseconn"
        assert api_key == "customer-authorized-value"
        return {
            "identity": {"provider": provider, "resource_count": 1},
            "resources": [{"id": "farm-1", "name": "Farm One", "type": "farm"}],
        }

    monkeypatch.setattr(connector_unified_v3, "_probe_candidate", fake_probe)
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


def test_failed_authorization_never_persists_candidate(monkeypatch):
    async def fail_probe(_provider, _api_key):
        from app.adapters.wiseconn import WiseConnAuthError
        raise WiseConnAuthError("denied")

    monkeypatch.setattr(connector_unified_v3, "_probe_candidate", fail_probe)
    client, SessionLocal = make_client(monkeypatch)
    response = client.post(
        "/v1/connectors/unified/connect",
        json={"provider": "wiseconn", "api_key": "bad-customer-value"},
    )
    assert response.status_code == 401
    assert "bad-customer-value" not in response.text
    assert response.json()["detail"]["code"] == "provider_authorization_failed"

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
            raise AssertionError("failed authorization candidate must never be persisted")


def test_failed_reauthorization_preserves_existing_valid_vault_record(monkeypatch):
    attempts = 0

    async def probe(provider, api_key):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"identity": {"provider": provider}, "resources": []}
        from app.adapters.wiseconn import WiseConnAuthError
        raise WiseConnAuthError("denied")

    monkeypatch.setattr(connector_unified_v3, "_probe_candidate", probe)
    client, SessionLocal = make_client(monkeypatch)

    first = client.post("/v1/connectors/unified/connect", json={"provider": "wiseconn", "api_key": "known-good-value"})
    assert first.status_code == 200, first.text
    connection_id = first.json()["connection"]["id"]

    replacement = client.post("/v1/connectors/unified/connect", json={"provider": "wiseconn", "api_key": "bad-replacement-value"})
    assert replacement.status_code == 401
    assert "bad-replacement-value" not in replacement.text

    with SessionLocal() as db:
        from app.models.operational_records import ConnectorConnection
        connection = db.get(ConnectorConnection, connection_id)
        assert connection is not None
        assert connection.credentials_ref
        assert connection.status == "connected"
        stored = load_connector_credentials(db, tenant_id="org-unified-v3", connection_id=connection_id)
        assert stored == {"api_key": "known-good-value"}


def test_controller_sync_requires_explicit_resource_scope(monkeypatch):
    install_success_probe(monkeypatch, resources=[{"id": "farm-1", "name": "Farm One", "type": "farm"}])
    client, _SessionLocal = make_client(monkeypatch)
    connected = client.post("/v1/connectors/unified/connect", json={"provider": "wiseconn", "api_key": "good-value"})
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["connection"]["id"]

    no_scope = client.post(f"/v1/connectors/unified/{connection_id}/sync")
    assert no_scope.status_code == 409
    assert no_scope.json()["detail"]["code"] == "connector_scope_required"

    empty_scope = client.post(
        f"/v1/connectors/unified/{connection_id}/selection",
        json={"scope_mode": "provider_resources", "resource_ids": []},
    )
    assert empty_scope.status_code == 422
    assert empty_scope.json()["detail"]["code"] == "provider_resource_selection_required"


def test_controller_selection_is_bounded_to_fifty_top_level_resources(monkeypatch):
    install_success_probe(monkeypatch)
    client, _SessionLocal = make_client(monkeypatch)
    connected = client.post("/v1/connectors/unified/connect", json={"provider": "wiseconn", "api_key": "good-value"})
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["connection"]["id"]

    scope = client.post(
        f"/v1/connectors/unified/{connection_id}/selection",
        json={"scope_mode": "provider_resources", "resource_ids": [f"farm-{index}" for index in range(75)]},
    )
    assert scope.status_code == 200, scope.text
    assert len(scope.json()["selection"]["resource_ids"]) == 50


def test_openet_sync_requires_confirmed_field_scope(monkeypatch):
    install_success_probe(monkeypatch, provider="openet")
    client, _SessionLocal = make_client(monkeypatch)
    connected = client.post("/v1/connectors/unified/connect", json={"provider": "openet", "api_key": "openet-value"})
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["connection"]["id"]

    no_scope = client.post(f"/v1/connectors/unified/{connection_id}/sync")
    assert no_scope.status_code == 409
    assert no_scope.json()["detail"]["code"] == "connector_scope_required"

    explicit = client.post(
        f"/v1/connectors/unified/{connection_id}/selection",
        json={"scope_mode": "openet_field_ids", "field_ids": ["oe-1", "oe-2"]},
    )
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["selection"]["field_ids"] == ["oe-1", "oe-2"]

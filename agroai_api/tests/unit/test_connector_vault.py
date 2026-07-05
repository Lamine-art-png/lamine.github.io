import base64
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.connector_security import ConnectorCredential
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, User, Workspace
from app.services.connector_vault import load_connector_credentials, revoke_connector_credentials, store_connector_credentials


def _setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Organization.__table__, Workspace.__table__, ConnectorConnection.__table__, ConnectorCredential.__table__])
    db = sessionmaker(bind=engine)()
    user = User(email="owner@example.com", password_hash="x")
    db.add(user)
    db.flush()
    org = Organization(name="Test Org", slug="test-org", owner_user_id=user.id)
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="North Farm")
    db.add(workspace)
    db.flush()
    connection = ConnectorConnection(tenant_id=org.id, workspace_id=workspace.id, provider="dropbox", display_name="Dropbox", status="oauth_pending", mode="oauth", required_plan="pro", config_json={})
    db.add(connection)
    db.commit()
    return db, org, connection


def _configure_key(monkeypatch, byte=b"k", version="v7"):
    encoded = base64.urlsafe_b64encode(byte * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", encoded)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", version)
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_KEYS_JSON", raising=False)


def test_vault_round_trip_without_clear_value_persistence(monkeypatch):
    _configure_key(monkeypatch)
    db, org, connection = _setup()
    payload = {"access_token": "value-one", "refresh_token": "value-two", "token_type": "bearer"}
    row = store_connector_credentials(db, tenant_id=org.id, connection=connection, provider="dropbox", payload=payload, scopes=["files.metadata.read"])
    db.commit()

    stored = json.dumps({"nonce": row.nonce_b64, "ciphertext": row.ciphertext_b64, "key_version": row.key_version})
    assert "value-one" not in stored
    assert "value-two" not in stored
    assert load_connector_credentials(db, tenant_id=org.id, connection_id=connection.id) == payload


def test_vault_revocation_removes_active_lookup(monkeypatch):
    _configure_key(monkeypatch)
    db, org, connection = _setup()
    store_connector_credentials(db, tenant_id=org.id, connection=connection, provider="dropbox", payload={"access_token": "value"})
    db.commit()
    assert revoke_connector_credentials(db, tenant_id=org.id, connection_id=connection.id) is True
    db.commit()
    with pytest.raises(LookupError):
        load_connector_credentials(db, tenant_id=org.id, connection_id=connection.id)


def test_vault_key_version_must_remain_available(monkeypatch):
    _configure_key(monkeypatch, byte=b"a", version="v1")
    db, org, connection = _setup()
    store_connector_credentials(db, tenant_id=org.id, connection=connection, provider="dropbox", payload={"access_token": "value"})
    db.commit()
    _configure_key(monkeypatch, byte=b"b", version="v2")
    with pytest.raises(RuntimeError):
        load_connector_credentials(db, tenant_id=org.id, connection_id=connection.id)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.connector_security import OAuthStateNonce
from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, User, Workspace
from app.services.oauth_state_store import consume_oauth_state, issue_oauth_state


def _setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Organization.__table__, Workspace.__table__, ConnectorConnection.__table__, OAuthStateNonce.__table__])
    db = sessionmaker(bind=engine)()
    user = User(email="owner@example.com", password_hash="x")
    db.add(user)
    db.flush()
    org = Organization(
        name="Test Org",
        slug="test-org",
        owner_user_id=user.id,
        plan="professional",
        subscription_status="active",
    )
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="North Farm")
    db.add(workspace)
    db.flush()
    connection = ConnectorConnection(tenant_id=org.id, workspace_id=workspace.id, provider="dropbox", display_name="Dropbox", status="oauth_pending", mode="oauth", required_plan="pro", config_json={})
    db.add(connection)
    db.commit()
    return db, org, connection


def test_state_is_bound_to_redirect_and_consumed_once(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SIGNING_KEY", "dedicated-state-signing-key-for-tests")
    db, org, connection = _setup()
    redirect = "https://api.example.test/callback"
    state = issue_oauth_state(db, connection=connection, tenant_id=org.id, provider="dropbox", redirect_url=redirect, ttl_seconds=300)
    db.commit()

    assert consume_oauth_state(db, state=state, redirect_url="https://other.example/callback") is None
    payload = consume_oauth_state(db, state=state, redirect_url=redirect)
    assert payload is not None
    assert payload["tid"] == org.id
    assert payload["provider"] == "dropbox"
    assert payload["cid"] == connection.id
    assert consume_oauth_state(db, state=state, redirect_url=redirect) is None


def test_state_rejects_provider_change(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SIGNING_KEY", "dedicated-state-signing-key-for-tests")
    db, org, connection = _setup()
    redirect = "https://api.example.test/callback"
    state = issue_oauth_state(db, connection=connection, tenant_id=org.id, provider="dropbox", redirect_url=redirect)
    db.commit()
    connection.provider = "box"
    db.commit()
    assert consume_oauth_state(db, state=state, redirect_url=redirect) is None

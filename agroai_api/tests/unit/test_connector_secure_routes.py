from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app


def _client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_current_tenant_id, None)


def test_account_connector_cannot_be_marked_connected_without_authorization():
    client = _client()
    try:
        response = client.post("/v1/connectors/connect", json={"provider": "dropbox", "config": {"account_hint": "ops@example.com"}})
    finally:
        _cleanup()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "authorization_required"
    assert body["connection"]["credentials_ref"] is None
    assert body["connection"]["live_sync_enabled"] is False


def test_oauth_start_uses_secure_route_without_fake_connection(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SIGNING_KEY", "dedicated-state-key-for-route-test")
    client = _client()
    try:
        response = client.post("/v1/connectors/oauth/start", json={"provider": "dropbox"})
    finally:
        _cleanup()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"oauth_pending", "platform_setup_required"}
    assert body["connection"]["credentials_ref"] is None
    assert body["status"] != "connected"

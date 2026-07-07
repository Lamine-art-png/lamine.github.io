from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import connector_launch as connector_launch_api
from app.api.v1.connector_launch import manifest_for
from app.api.v1.connectors import CATALOG, oauth_url
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.connector_security import OAuthStateNonce
from app.models.saas import Organization, User
from app.services.oauth_state import sign_oauth_state, verify_oauth_state
from app.services.oauth_state_store import _decode, _digest


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        owner = User(id="owner-test", email="owner@example.com", password_hash="x")
        db.add(owner)
        db.flush()
        db.add(
            Organization(
                id="org-test",
                name="Connector Runtime Test Org",
                slug="connector-runtime-test-org",
                owner_user_id=owner.id,
                plan="professional",
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
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    client = TestClient(app)
    client.testing_session_local = TestingSessionLocal
    return client


def test_catalog_includes_connector_runtime_v21_providers():
    providers = {item["id"] for item in CATALOG}
    assert {"dropbox", "box", "slack", "salesforce", "google_earth_engine"}.issubset(providers)


def test_catalog_readiness_reports_missing_env_names_without_values():
    client = make_client()
    response = client.get("/v1/connectors/catalog")
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["connectors"]}
    assert by_id["dropbox"]["missing_env"] == ["DROPBOX_OAUTH_CLIENT_ID"]
    assert "DROPBOX_OAUTH_CLIENT_ID" not in str(by_id["dropbox"].get("config_json", ""))
    assert by_id["google_earth_engine"]["missing_env"] == [
        "GOOGLE_EARTH_ENGINE_PROJECT_ID",
        "GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON",
    ]


def test_dropbox_oauth_url_uses_configured_client_id(monkeypatch):
    monkeypatch.setenv("DROPBOX_OAUTH_CLIENT_ID", "dropbox-client")
    url, error = oauth_url("dropbox", "opaque-state", "https://api.example.com/callback")
    assert error is None
    assert url is not None
    assert url.startswith("https://www.dropbox.com/oauth2/authorize?")
    assert "client_id=dropbox-client" in url
    assert "state=opaque-state" in url


def test_launch_start_uses_one_time_state_and_callback_hides_raw_code(monkeypatch):
    monkeypatch.setenv("SLACK_OAUTH_CLIENT_ID", "slack-client")
    monkeypatch.setenv("OAUTH_STATE_SIGNING_KEY", "dedicated-launch-state-signing-key")
    monkeypatch.setenv("SLACK_OAUTH_REDIRECT_URI", "https://api.example.test/v1/connectors/oauth/callback")
    client = make_client()
    started = client.post("/v1/connectors/launch/start", json={"provider": "slack"})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["auth_url"]
    assert "org-test" not in body["auth_url"]
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]
    assert ":" not in state
    assert "oauth_state" not in str(body["connection"]["config_json"])

    # Pin the exact security invariants before the callback crosses sessions.
    assert connector_launch_api._consume_state_for_known_callback.__name__ == "exact_callback_consumer"
    decoded = _decode(state)
    assert decoded is not None
    assert decoded["provider"] == "slack"
    exact_redirect = connector_launch_api.callback_url_for("slack")
    assert decoded["redirect_sha256"] == _digest(exact_redirect.strip())
    with client.testing_session_local() as db:
        nonce = (
            db.query(OAuthStateNonce)
            .filter(OAuthStateNonce.nonce_hash == _digest(str(decoded["nonce"])))
            .first()
        )
        assert nonce is not None
        assert nonce.consumed_at is None
        assert nonce.redirect_sha256 == decoded["redirect_sha256"]

    connection_id = body["connection"]["id"]
    callback = client.get("/v1/connectors/oauth/callback", params={"state": state, "code": "raw-oauth-code"})
    assert callback.status_code == 200
    assert "Authorization was received" in callback.text
    assert "raw-oauth-code" not in callback.text

    fetched = client.get(f"/v1/connectors/connections/{connection_id}")
    assert fetched.status_code == 200
    config = fetched.json()["connection"]["config_json"]
    assert config["oauth_code_present"] is True
    assert config["authorization_status"] == "authorized_pending_token_exchange"
    assert "raw-oauth-code" not in str(config)

    replay = client.get("/v1/connectors/oauth/callback", params={"state": state, "code": "another-code"})
    assert replay.status_code == 200
    assert "invalid, expired, or already used" in replay.text


def test_legacy_signer_still_rejects_tampering_for_non_custody_compatibility():
    state = sign_oauth_state("connection-123")
    assert ":" not in state
    verified = verify_oauth_state(state)
    assert verified is not None
    assert verified["cid"] == "connection-123"
    assert verify_oauth_state(state[:-1] + ("0" if state[-1] != "0" else "1")) is None


def test_google_earth_engine_manifest_ready_without_exposing_service_account(monkeypatch):
    monkeypatch.setenv("GOOGLE_EARTH_ENGINE_PROJECT_ID", "agroai-project")
    monkeypatch.setenv("GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON", '{"private_key":"secret"}')
    manifest = manifest_for("google_earth_engine")
    assert manifest["configured"] is True
    assert manifest["readiness"] == "service_account_ready"
    assert "secret" not in str(manifest)

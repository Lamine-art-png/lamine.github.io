from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app
from app.models.saas import Organization


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(
            Organization(
                id="org-test",
                name="Connector Test Org",
                slug="connector-test-org",
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
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    return TestClient(app)


def test_gmail_without_oauth_platform_config_never_fake_connects(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SIGNING_KEY", "dedicated-test-state-key")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    client = make_client()
    response = client.post(
        "/v1/connectors/oauth/start",
        json={"provider": "gmail", "metadata": {"account_hint": "ops@example.com"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["connection"]["provider"] == "gmail"
    assert body["connection"]["status"] == "platform_setup_required"
    assert body["connection"]["credentials_ref"] is None
    assert body["auth_url"] is None


def test_direct_evidence_upload_creates_records():
    client = make_client()
    csv_body = (
        "timestamp,field,block,crop,flow_gpm,duration_minutes,water_gallons,note\n"
        "2026-06-26 06:00:00,North Ranch,Block A,Almonds,420,45,18900,ok\n"
    )
    response = client.post(
        "/v1/evidence/upload?provider=manual_csv",
        files={"file": ("sample.csv", BytesIO(csv_body.encode()), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows_parsed"] == 1
    assert body["evidence_records_created"] == 1
    assert body["connection"]["status"] == "synced"


def test_custom_api_secret_uses_encrypted_runtime_vault_fallback(monkeypatch):
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_MASTER_KEY", raising=False)
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_KEYS_JSON", raising=False)
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", raising=False)
    client = make_client()
    response = client.post(
        "/v1/connectors/connect",
        json={
            "provider": "custom_api",
            "config": {
                "provider_name": "Ranch Systems",
                "base_url": "https://api.example.com",
                "credential_ref": "example-provider-value",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "connected"
    assert str(body["connection"]["credentials_ref"]).startswith("vault://connector-credentials/")


def test_custom_api_secret_is_vaulted_before_connected(monkeypatch):
    key = base64.urlsafe_b64encode(b"q" * 32).decode("ascii").rstrip("=")
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION", "v1")
    monkeypatch.delenv("CONNECTOR_CREDENTIAL_KEYS_JSON", raising=False)
    client = make_client()
    response = client.post(
        "/v1/connectors/connect",
        json={
            "provider": "custom_api",
            "config": {
                "provider_name": "Ranch Systems",
                "base_url": "https://api.example.com",
                "credential_ref": "example-provider-value",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "connected"
    assert body["connection"]["provider"] == "custom_api"
    assert str(body["connection"]["credentials_ref"]).startswith("vault://connector-credentials/")

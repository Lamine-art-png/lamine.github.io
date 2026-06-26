from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.main import app


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_current_tenant_id] = lambda: "org-test"
    return TestClient(app)


def test_gmail_connects_in_internal_mode_without_oauth_env():
    client = make_client()
    response = client.post(
        "/v1/connectors/oauth/start",
        json={"provider": "gmail", "metadata": {"account_hint": "ops@example.com"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["connection"]["provider"] == "gmail"
    assert body["connection"]["status"] == "connected"
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


def test_custom_api_connect_marks_provider_connected():
    client = make_client()
    response = client.post(
        "/v1/connectors/connect",
        json={
            "provider": "custom_api",
            "config": {
                "provider_name": "Ranch Systems",
                "base_url": "https://api.example.com",
                "credential_ref": "secret-token",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["connection"]["provider"] == "custom_api"
    assert body["connection"]["status"] == "connected"

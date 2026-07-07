from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.operational_records import ConnectorConnection
from app.models.saas import EntitlementOverride, Organization, User
from app.services import provider_sync_runner


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    owner = User(id="owner-worker-v3", email="worker-v3@example.com", password_hash="x")
    db.add(owner)
    db.flush()
    org = Organization(
        id="org-worker-v3",
        name="Worker V3 Test Org",
        slug="worker-v3-test-org",
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
            reason="Exercise provider worker lifecycle.",
        )
    )
    connection = ConnectorConnection(
        tenant_id=org.id,
        provider="wiseconn",
        display_name="WiseConn",
        status="syncing",
        mode="api_key",
        required_plan="professional",
        credentials_ref="vault://connector-credentials/test",
        config_json={},
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return db, connection


def test_retrying_provider_failure_marks_connection_degraded(monkeypatch):
    db, connection = make_session()
    monkeypatch.setattr(provider_sync_runner, "_fail_or_retry", lambda *_args, **_kwargs: "retrying")
    try:
        result = provider_sync_runner._retry_with_connection_state(
            db,
            job_id="job-v3",
            connection_id=connection.id,
            tenant_id=connection.tenant_id,
            worker_id="worker-v3",
            exc=RuntimeError("upstream unavailable"),
            retry_state="degraded",
        )
        assert result == "retrying"
        db.refresh(connection)
        assert connection.status == "degraded"
        assert "upstream unavailable" in str(connection.last_error)
    finally:
        db.close()


def test_rate_limited_retry_keeps_truthful_rate_limited_state(monkeypatch):
    db, connection = make_session()
    monkeypatch.setattr(provider_sync_runner, "_fail_or_retry", lambda *_args, **_kwargs: "retrying")
    try:
        result = provider_sync_runner._retry_with_connection_state(
            db,
            job_id="job-v3",
            connection_id=connection.id,
            tenant_id=connection.tenant_id,
            worker_id="worker-v3",
            exc=RuntimeError("provider quota reached"),
            retry_state="rate_limited",
        )
        assert result == "retrying"
        db.refresh(connection)
        assert connection.status == "rate_limited"
    finally:
        db.close()


def test_exhausted_provider_failure_marks_connection_failed(monkeypatch):
    db, connection = make_session()
    monkeypatch.setattr(provider_sync_runner, "_fail_or_retry", lambda *_args, **_kwargs: "failed")
    try:
        result = provider_sync_runner._retry_with_connection_state(
            db,
            job_id="job-v3",
            connection_id=connection.id,
            tenant_id=connection.tenant_id,
            worker_id="worker-v3",
            exc=RuntimeError("retry budget exhausted"),
            retry_state="degraded",
        )
        assert result == "failed"
        db.refresh(connection)
        assert connection.status == "failed"
    finally:
        db.close()

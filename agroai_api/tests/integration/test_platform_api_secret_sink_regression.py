"""Sink-oriented secret-leak regression suite.

Proves that Platform API secrets never reach observability/persistence sinks:
Prometheus metric labels (low-cardinality, no customer identifiers), the
persisted request log, the /metrics exposition, or error responses. Complements
the response-redaction unit tests and the repository secret scanner.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()

# Prometheus labels must never carry high-cardinality customer input.
ALLOWED_METRIC_LABELS = {
    "environment", "outcome", "subsystem", "action", "event_class",
    "backend", "dimension", "reason", "result",
}
FORBIDDEN_LABEL_SUBSTRINGS = ("organization", "org_id", "api_key", "key_id", "project", "customer", "user", "email", "ip")


def test_platform_metric_labels_are_low_cardinality_and_carry_no_customer_identifiers():
    from app.core import metrics

    checked = 0
    for name in dir(metrics):
        obj = getattr(metrics, name)
        labelnames = getattr(obj, "_labelnames", None)
        if not labelnames:
            continue
        metric_name = getattr(obj, "_name", "") or ""
        if "platform" not in metric_name and "platform" not in name.lower():
            continue
        checked += 1
        for label in labelnames:
            assert label in ALLOWED_METRIC_LABELS, f"{metric_name}: unexpected label '{label}'"
            assert not any(bad in label.lower() for bad in FORBIDDEN_LABEL_SUBSTRINGS), (
                f"{metric_name}: label '{label}' looks like a customer identifier"
            )
    assert checked >= 4  # authentication, product_events, quota_decisions, rate_limit, ...


@pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")
def test_full_key_never_reaches_request_log_metrics_or_error_bodies(monkeypatch):
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app
    from app.models.saas import Organization, OrganizationMembership, User, Workspace
    from app.models.platform_api import ApiProject, ApiServiceAccount
    from app.models.platform_product import PlatformProgramEnrollment, PlatformRequestLog
    from app.platform_api.keys import create_platform_key

    for name in ("PLATFORM_API_ENABLED", "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED"):
        monkeypatch.setattr(settings, name, True, raising=False)

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"sink-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        org = Organization(name=f"Sink {s}", slug=f"sink-{s}", owner_user_id=user.id,
                           plan="developer", subscription_status="active", verification_status="approved")
        db.add(org); db.flush()
        ws = Workspace(organization_id=org.id, name="w", mode="evaluation")
        db.add(ws); db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.add(PlatformProgramEnrollment(
            organization_id=org.id, program="developer_self_service", status="active",
            approved_at=datetime.utcnow(), allowed_environments_json=["test"],
            maximum_projects=5, maximum_service_accounts=5, maximum_keys=10, effective_at=datetime.utcnow(),
        ))
        project = ApiProject(organization_id=org.id, workspace_id=ws.id, name="p", slug=f"p-{s}",
                             environment="test", status="active", default_rate_limit_policy={}, created_by_user_id=user.id)
        db.add(project); db.flush()
        sa = ApiServiceAccount(organization_id=org.id, api_project_id=project.id, workspace_id=ws.id,
                               name="sa", status="active", scopes=["projects:read", "fields:read"], created_by_user_id=user.id)
        db.add(sa); db.flush()
        key, plaintext = create_platform_key(db, project=project, service_account=sa, name="k",
                                             scopes=["projects:read", "fields:read"], created_by_user_id=user.id, workspace_id=ws.id)
        db.commit()
        org_id, project_id = org.id, project.id
    finally:
        db.close()

    def override_get_db():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        # Successful authenticated call (creates a request log row).
        ok = client.get("/v1/platform/me", headers={"Authorization": f"Bearer {plaintext}"})
        assert ok.status_code == 200
        # Failed call with the SAME secret in the Authorization header + a bogus one.
        bad = client.get("/v1/platform/fields", headers={"Authorization": "Bearer " + plaintext + "TAMPERED"})
        assert bad.status_code in (401, 403)
        assert plaintext not in bad.text  # error body never echoes the key

        # 1. Persisted request log holds only the safe fingerprint, never the key.
        db = Session()
        try:
            logs = db.query(PlatformRequestLog).filter(PlatformRequestLog.organization_id == org_id).all()
            assert logs, "expected at least one persisted request log"
            for row in logs:
                assert plaintext not in (row.key_fingerprint or "")
                assert row.key_fingerprint is None or len(row.key_fingerprint) <= 32
                # No column serialization carries the plaintext.
                assert plaintext not in repr({c.name: getattr(row, c.name) for c in row.__table__.columns})
        finally:
            db.close()

        # 2. /metrics exposition never contains the key or a live-secret shape.
        metrics_text = client.get("/metrics").text
        assert plaintext not in metrics_text
        assert "agro_test_" not in metrics_text and "agro_live_" not in metrics_text
    finally:
        app.dependency_overrides.pop(get_db, None)

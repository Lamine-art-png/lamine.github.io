"""Exhaustive cross-organization / cross-project BOLA-IDOR matrix (real PG).

For every customer-accessible Platform resource, proves that Organization A's
credentials can never read, update, delete, or enumerate Organization B's
resources by supplying a copied/guessed id — i.e. the authorization predicate is
derived from the authenticated principal, not from client-supplied ids. Covers
direct-id endpoints AND list endpoints.
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
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")

FLAGS_ON = (
    "PLATFORM_API_ENABLED",
    "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED",
    "PLATFORM_API_TEST_PROJECTS_ENABLED",
    "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED",
)
SCOPES = [
    "projects:read", "service_accounts:read", "keys:read", "keys:write",
    "fields:read", "fields:write", "sources:read", "sources:write",
    "observations:read", "observations:write", "recommendations:read", "recommendations:write",
    "reports:read", "reports:write", "jobs:read", "usage:read", "request_logs:read",
]


def _provision(Session):
    """Directly provision org + approved verification + active TEST enrollment +
    project + service account + agro_test_ key + owner user. Returns a dict."""
    from app.models.saas import Organization, OrganizationMembership, User, Workspace
    from app.models.platform_api import ApiProject, ApiServiceAccount
    from app.models.platform_product import PlatformProgramEnrollment
    from app.platform_api.keys import create_platform_key

    db = Session()
    try:
        s = uuid.uuid4().hex[:8]
        user = User(email=f"bola-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user); db.flush()
        org = Organization(name=f"Bola {s}", slug=f"bola-{s}", owner_user_id=user.id,
                           plan="developer", subscription_status="active", verification_status="approved")
        db.add(org); db.flush()
        ws = Workspace(organization_id=org.id, name="w", mode="evaluation")
        db.add(ws); db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.add(PlatformProgramEnrollment(
            organization_id=org.id, program="developer_self_service", status="active",
            approved_at=datetime.utcnow(), allowed_environments_json=["test"],
            maximum_projects=5, maximum_live_projects=0, maximum_service_accounts=5,
            maximum_keys=10, maximum_webhooks=3, effective_at=datetime.utcnow(),
        ))
        project = ApiProject(organization_id=org.id, workspace_id=ws.id, name="p",
                             slug=f"p-{s}", environment="test", status="active",
                             default_rate_limit_policy={}, created_by_user_id=user.id)
        db.add(project); db.flush()
        sa = ApiServiceAccount(organization_id=org.id, api_project_id=project.id, workspace_id=ws.id,
                               name="sa", status="active", scopes=SCOPES, created_by_user_id=user.id)
        db.add(sa); db.flush()
        key, plaintext = create_platform_key(db, project=project, service_account=sa, name="k",
                                             scopes=SCOPES, created_by_user_id=user.id, workspace_id=ws.id)
        db.commit()
        from app.core.security import create_access_token
        return {
            "user_id": user.id, "org_id": org.id, "project_id": project.id,
            "service_account_id": sa.id, "key_id": key.id, "plaintext": plaintext,
            "jwt": {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"},
            "key_hdr": {"Authorization": f"Bearer {plaintext}"},
        }
    finally:
        db.close()


def test_cross_org_bola_idor_matrix(monkeypatch):
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for name in FLAGS_ON:
        monkeypatch.setattr(settings, name, True, raising=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        A = _provision(Session)
        B = _provision(Session)
        idem = lambda: {"Idempotency-Key": uuid.uuid4().hex}

        # --- Seed resources owned by B (via B's own key) ---
        fB = client.post("/v1/platform/fields", headers={**B["key_hdr"], **idem()},
                         json={"name": "B field", "crop": "corn", "area_hectares": 5.0})
        assert fB.status_code == 201, fB.text
        field_b = fB.json()["field"]["id"]

        sB = client.post("/v1/platform/sources", headers={**B["key_hdr"], **idem()},
                         json={"source_type": "telemetry", "provider": "customer_upload"})
        assert sB.status_code in (200, 201), sB.text
        source_b = sB.json()["source"]["id"]

        rB = client.post("/v1/platform/reports", headers={**B["key_hdr"], **idem()},
                         json={"title": "B report", "field_ids": [field_b]})
        assert rB.status_code == 202, rB.text
        job_b = rB.json()["job"]["id"]

        # --- A must NOT reach any of B's resources by id (expect 404, never 200) ---
        direct_id_cases = [
            ("GET", f"/v1/platform/fields/{field_b}", None),
            ("PATCH", f"/v1/platform/fields/{field_b}", {"crop": "hacked"}),
            ("DELETE", f"/v1/platform/fields/{field_b}", None),
            ("GET", f"/v1/platform/sources/{source_b}", None),
            ("GET", f"/v1/platform/jobs/{job_b}", None),
            ("GET", f"/v1/platform/reports/{job_b}", None),
            ("POST", f"/v1/platform/jobs/{job_b}/retry", {}),
        ]
        for method, path, body in direct_id_cases:
            hdrs = dict(A["key_hdr"])
            if method in ("PATCH", "POST", "DELETE"):
                hdrs.update(idem())
            resp = client.request(method, path, headers=hdrs, json=body)
            assert resp.status_code == 404, f"BOLA LEAK {method} {path} -> {resp.status_code}: {resp.text}"
            assert field_b not in resp.text and source_b not in resp.text and job_b not in resp.text

        # --- A's list endpoints must never enumerate B's resources ---
        list_paths = [
            "/v1/platform/fields", "/v1/platform/sources", "/v1/platform/observations",
            "/v1/platform/recommendations", "/v1/platform/reports", "/v1/platform/jobs",
            "/v1/platform/request-logs",
        ]
        for path in list_paths:
            resp = client.get(path, headers=A["key_hdr"])
            assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text}"
            text = resp.text
            assert field_b not in text and source_b not in text and job_b not in text, f"ENUMERATION LEAK in {path}"

        # --- Control-plane (human JWT): A cannot touch B's control-plane objects ---
        cp_cases = [
            ("GET", f"/v1/platform/developer/projects/{B['project_id']}", None),
            ("PATCH", f"/v1/platform/developer/projects/{B['project_id']}", {"name": "hijacked"}),
            ("POST", f"/v1/platform/developer/keys/{B['key_id']}/revoke", None),
            ("POST", f"/v1/platform/developer/keys/{B['key_id']}/rotate", {"overlap_minutes": 0}),
        ]
        for method, path, body in cp_cases:
            resp = client.request(method, path, headers=A["jwt"], json=body)
            assert resp.status_code == 404, f"CONTROL-PLANE BOLA {method} {path} -> {resp.status_code}: {resp.text}"

        # --- Sanity: B CAN reach its own resources (predicate is principal-derived, not blanket-deny) ---
        assert client.get(f"/v1/platform/fields/{field_b}", headers=B["key_hdr"]).status_code == 200
        assert client.get(f"/v1/platform/developer/projects/{B['project_id']}", headers=B["jwt"]).status_code == 200

        # --- B's key still cannot escalate to a copied A id either (symmetry) ---
        fA = client.post("/v1/platform/fields", headers={**A["key_hdr"], **idem()},
                         json={"name": "A field", "area_hectares": 2.0})
        assert fA.status_code == 201
        field_a = fA.json()["field"]["id"]
        assert client.get(f"/v1/platform/fields/{field_a}", headers=B["key_hdr"]).status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)

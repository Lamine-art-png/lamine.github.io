"""Adversarial HTTP matrix for the paid AGRO-AI Intelligence API (real PG).

Every attack goes through the real FastAPI application, real API-key
verification, the credential guard, and the hardened money path. Each rejected
attack must leave the wallet untouched and must never reach the model; foreign
identifiers must fail exactly like identifiers that do not exist, so the API is
not an existence oracle for other tenants' resources.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")

FLAGS_ON = ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED")
PRICE_ANSWER = 5


def _tenant(Session, *, balance_cents: int):
    from app.core.security import create_access_token
    from app.models.intelligence_commerce import IntelligenceWallet
    from app.models.saas import ManagedEntity, Organization, OrganizationMembership, User, Workspace

    db = Session()
    try:
        s = uuid.uuid4().hex[:10]
        user = User(
            email=f"intel-attack-{s}@example.com",
            password_hash="x",
            email_verification_status="verified",
            email_verified_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()
        org = Organization(
            name=f"Intel attack {s}",
            slug=f"intel-attack-{s}",
            owner_user_id=user.id,
            plan="enterprise",
            subscription_status="active",
            verification_status="approved",
        )
        db.add(org)
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        ws_main = Workspace(organization_id=org.id, name="main", mode="evaluation")
        ws_other = Workspace(organization_id=org.id, name="other", mode="evaluation")
        db.add_all([ws_main, ws_other])
        db.flush()
        field_other = ManagedEntity(
            organization_id=org.id,
            workspace_id=ws_other.id,
            entity_type="platform_field",
            display_name="Other block",
            status="active",
            metadata_json={"crop": "almond"},
        )
        db.add(field_other)
        db.add(IntelligenceWallet(organization_id=org.id, currency="usd", balance_cents=balance_cents,
                                  lifetime_funded_cents=balance_cents, lifetime_spent_cents=0))
        db.commit()
        return SimpleNamespace(
            org_id=org.id,
            user_id=user.id,
            ws_main=ws_main.id,
            ws_other=ws_other.id,
            field_other=field_other.id,
            jwt={"Authorization": f"Bearer {create_access_token({'sub': user.id})}"},
            balance=balance_cents,
        )
    finally:
        db.close()


def _wallet_state(Session, org_id: str):
    from app.models.intelligence_commerce import IntelligenceWallet, IntelligenceWalletLedger

    db = Session()
    try:
        wallet = db.query(IntelligenceWallet).filter_by(organization_id=org_id).one()
        charges = (
            db.query(IntelligenceWalletLedger)
            .filter_by(organization_id=org_id, kind="intelligence_charge", status="posted")
            .count()
        )
        return wallet.balance_cents, wallet.lifetime_spent_cents, charges
    finally:
        db.close()


def _cleanup(Session, org_ids, user_ids):
    from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWallet, IntelligenceWalletLedger
    from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
    from app.models.saas import ManagedEntity, Organization, OrganizationMembership, User, Workspace

    db = Session()
    try:
        for model in (
            IntelligenceWalletLedger,
            CommercialIntelligenceRun,
            IntelligenceWallet,
            PlatformApiKey,
            ApiServiceAccount,
            ApiProject,
            ManagedEntity,
            OrganizationMembership,
            Workspace,
        ):
            db.query(model).filter(model.organization_id.in_(org_ids)).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id.in_(org_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def test_paid_intelligence_attack_matrix(monkeypatch):
    from app.api.v1 import commercial_intelligence as legacy
    from app.core.config import settings
    from app.db.base import get_db
    from app.main import app
    from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
    from app.platform_api.keys import create_platform_key

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for name in FLAGS_ON:
        monkeypatch.setattr(settings, name, True, raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False, raising=False)

    model_calls: list[str] = []

    async def model_ok(**kwargs):
        model_calls.append(kwargs.get("user_instruction", ""))
        return (
            {"answer": "Irrigate the north block after the soil-moisture check.", "confidence": "medium"},
            SimpleNamespace(status="ok", demo_fallback=False, provider="test-provider", model="test-model"),
        )

    monkeypatch.setattr(legacy, "_run_ai", model_ok)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    A = _tenant(Session, balance_cents=100)
    B = _tenant(Session, balance_cents=100)
    try:
        idem = lambda: {"Idempotency-Key": uuid.uuid4().hex}
        ask = {"task": "answer", "question": "What needs attention?", "input": {"crop": "almond"}}

        # The real self-service path mints a restricted LIVE advisory key once.
        boot = client.post("/v1/platform/developer/intelligence/bootstrap", headers=A.jwt, json={})
        assert boot.status_code == 200, boot.text
        key = boot.json()["key"]
        assert key["one_time_display"] is True and key["secret"].startswith("agro_live_")
        assert key["scopes"] == ["intelligence:run"]
        assert boot.json()["physical_execution"] == "not_granted"
        again = client.post("/v1/platform/developer/intelligence/bootstrap", headers=A.jwt, json={})
        assert again.status_code == 200 and again.json()["key"]["secret"] is None, "secret must be shown once"
        a_key = {"Authorization": f"Bearer {key['secret']}"}
        project_id = boot.json()["project"]["id"]

        # Extra credentials for the matrix, provisioned beside the default advisory identity.
        db = Session()
        try:
            project = db.get(ApiProject, project_id)
            advisory_sa = db.query(ApiServiceAccount).filter_by(api_project_id=project_id).one()
            ws_key, ws_secret = create_platform_key(
                db, project=project, service_account=advisory_sa, name="main-only",
                scopes=["intelligence:run"], created_by_user_id=A.user_id, workspace_id=A.ws_main,
            )
            wrong_scope_sa = ApiServiceAccount(
                organization_id=A.org_id, api_project_id=project_id, workspace_id=None,
                name="reader", status="active", scopes=["fields:read"], created_by_user_id=A.user_id,
            )
            db.add(wrong_scope_sa)
            db.flush()
            _wrong_scope_key, wrong_scope_secret = create_platform_key(
                db, project=project, service_account=wrong_scope_sa, name="reader",
                scopes=["fields:read"], created_by_user_id=A.user_id,
            )
            test_project = ApiProject(
                organization_id=A.org_id, workspace_id=None, name="Sandbox", slug=f"sandbox-{uuid.uuid4().hex[:6]}",
                environment="test", status="active", default_rate_limit_policy={}, created_by_user_id=A.user_id,
            )
            db.add(test_project)
            db.flush()
            test_sa = ApiServiceAccount(
                organization_id=A.org_id, api_project_id=test_project.id, workspace_id=None,
                name="sandbox", status="active", scopes=["intelligence:run"], created_by_user_id=A.user_id,
            )
            db.add(test_sa)
            db.flush()
            _test_key, test_secret = create_platform_key(
                db, project=test_project, service_account=test_sa, name="sandbox",
                scopes=["intelligence:run"], created_by_user_id=A.user_id,
            )
            revoked_key, revoked_secret = create_platform_key(
                db, project=project, service_account=advisory_sa, name="to-revoke",
                scopes=["intelligence:run"], created_by_user_id=A.user_id,
            )
            db.commit()
            ws_key_id, revoked_key_id = ws_key.id, revoked_key.id
        finally:
            db.close()

        def reject(headers, body, status, code=None):
            calls_before = len(model_calls)
            resp = client.post("/v1/intelligence", headers={**headers, **idem()}, json=body)
            assert resp.status_code == status, (body, resp.status_code, resp.text)
            if code is not None:
                assert code in resp.text, resp.text
            assert len(model_calls) == calls_before, f"model reached by rejected request: {body}"
            for foreign in (B.org_id, B.ws_main, B.ws_other, B.field_other):
                assert foreign not in resp.text
            return resp

        # --- Authentication boundary ---
        reject({}, ask, 401)
        reject({"Authorization": "Bearer"}, ask, 401)
        reject({"Authorization": "Bearer not-a-key"}, ask, 401)
        reject({"Authorization": "Bearer agro_live_" + "0" * 40}, ask, 401, "invalid_api_key")
        reject({"Authorization": "Basic " + key["secret"]}, ask, 401)
        reject(A.jwt, ask, 401)  # a portal session is not an API key
        reject({"Authorization": f"Bearer {test_secret}"}, ask, 403, "live_advisory_key_required")
        reject({"Authorization": f"Bearer {wrong_scope_secret}"}, ask, 403)

        # --- Tenancy: foreign ids fail exactly like nonexistent ids ---
        missing_ws = reject(a_key, {**ask, "workspace_id": str(uuid.uuid4())}, 404, "workspace_not_found")
        foreign_ws = reject(a_key, {**ask, "workspace_id": B.ws_main}, 404, "workspace_not_found")
        assert foreign_ws.json() == missing_ws.json()
        missing_field = reject(a_key, {**ask, "field_id": str(uuid.uuid4())}, 404, "field_not_found")
        foreign_field = reject(a_key, {**ask, "field_id": B.field_other}, 404, "field_not_found")
        assert foreign_field.json() == missing_field.json()
        reject(a_key, {**ask, "field_id": B.field_other, "workspace_id": A.ws_main}, 404, "field_not_found")

        # --- Workspace-restricted key cannot be steered elsewhere ---
        ws_hdr = {"Authorization": f"Bearer {ws_secret}"}
        reject(ws_hdr, {**ask, "workspace_id": A.ws_other}, 403, "workspace_restricted")
        reject(ws_hdr, {**ask, "field_id": A.field_other}, 404, "field_not_found")
        reject(ws_hdr, {**ask, "workspace_id": B.ws_main}, 403, "workspace_restricted")

        # --- Credentials never reach inference, however deeply nested ---
        nested = {"crop": "almond", "a": {"b": [{"c": {"d": {"controller_api_key": "x"}}}]}}
        reject(a_key, {**ask, "input": nested}, 422, "credential_like_input_rejected")
        reject(a_key, {**ask, "input": {"notes": ["key " + "sk_" + "live_" + "a1B2c3D4e5F6g7H8"]}}, 422)
        reject(a_key, {**ask, "input": {"Telemetry-Password": "hunter2"}}, 422)
        reject(a_key, {**ask, "input": {"gateway": {"refresh_token": "abc"}}}, 422)
        reject(a_key, {**ask, "question": "Use Bear" + "er " + "abcdefghijklmnop" + "qrstuvwxyz0123"}, 422)

        assert _wallet_state(Session, A.org_id) == (100, 0, 0), "rejected attacks must not move money"
        assert model_calls == []

        # --- Legitimate run charges once; replay is free and identical ---
        run_key = {"Idempotency-Key": f"legit-{uuid.uuid4().hex}"}
        first = client.post("/v1/intelligence", headers={**a_key, **run_key}, json=ask)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["model"] == "agroai-intelligence-1" and body["billing"]["charged_cents"] == PRICE_ANSWER
        assert "test-provider" not in first.text and "test-model" not in first.text, "internal provider leaked"
        replay = client.post("/v1/intelligence", headers={**a_key, **run_key}, json=ask)
        assert replay.status_code == 200 and replay.json() == body
        assert len(model_calls) == 1
        changed = client.post("/v1/intelligence", headers={**a_key, **run_key}, json={**ask, "question": "Different?"})
        assert changed.status_code == 409 and "idempotency_key_reused_with_different_request" in changed.text
        assert _wallet_state(Session, A.org_id) == (100 - PRICE_ANSWER, PRICE_ANSWER, 1)

        # --- Replay after the replaying credential is narrowed to another workspace ---
        ws_run = {"Idempotency-Key": f"ws-{uuid.uuid4().hex}"}
        assert client.post("/v1/intelligence", headers={**ws_hdr, **ws_run}, json=ask).status_code == 200
        db = Session()
        try:
            restricted = db.get(PlatformApiKey, ws_key_id)
            restricted.workspace_id = A.ws_other
            db.commit()
        finally:
            db.close()
        narrowed = client.post("/v1/intelligence", headers={**ws_hdr, **ws_run}, json=ask)
        assert narrowed.status_code == 403 and "workspace_restricted" in narrowed.text
        assert len(model_calls) == 2
        assert _wallet_state(Session, A.org_id) == (100 - 2 * PRICE_ANSWER, 2 * PRICE_ANSWER, 2)

        # --- Replay after revocation: the cached result is not an authorization grant ---
        revoked_hdr = {"Authorization": f"Bearer {revoked_secret}"}
        revoked_run = {"Idempotency-Key": f"revoked-{uuid.uuid4().hex}"}
        assert client.post("/v1/intelligence", headers={**revoked_hdr, **revoked_run}, json=ask).status_code == 200
        db = Session()
        try:
            row = db.get(PlatformApiKey, revoked_key_id)
            row.status = "revoked"
            row.revoked_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        after_revoke = client.post("/v1/intelligence", headers={**revoked_hdr, **revoked_run}, json=ask)
        assert after_revoke.status_code == 401
        assert body["decision"] not in after_revoke.text
        assert _wallet_state(Session, A.org_id) == (100 - 3 * PRICE_ANSWER, 3 * PRICE_ANSWER, 3)

        # --- Browser path: org A's admin cannot reach org B; low balance never reaches the model ---
        foreign_browser = client.post(
            "/v1/platform/developer/intelligence/run",
            headers={**A.jwt, **idem()},
            json={**ask, "workspace_id": B.ws_main},
        )
        assert foreign_browser.status_code == 404 and B.ws_main not in foreign_browser.text
        calls_before = len(model_calls)
        boot_b = client.post("/v1/platform/developer/intelligence/bootstrap", headers=B.jwt, json={})
        assert boot_b.status_code == 200
        db = Session()
        try:
            from app.models.intelligence_commerce import IntelligenceWallet

            db.query(IntelligenceWallet).filter_by(organization_id=B.org_id).update({"balance_cents": 4})
            db.commit()
        finally:
            db.close()
        poor = client.post(
            "/v1/platform/developer/intelligence/run", headers={**B.jwt, **idem()}, json=ask
        )
        assert poor.status_code == 402 and "insufficient_intelligence_balance" in poor.text
        assert len(model_calls) == calls_before

        # --- Operator suspension: keys stop, and no self-service path can lift it ---
        db = Session()
        try:
            db.get(ApiProject, project_id).status = "suspended"
            db.commit()
        finally:
            db.close()
        reject(a_key, ask, 401)
        for path, body in (
            ("/v1/platform/developer/intelligence/bootstrap", {"create_new_key": True}),
            ("/v1/platform/developer/intelligence/run", ask),
        ):
            resp = client.post(path, headers={**A.jwt, **idem()}, json=body)
            assert resp.status_code == 403 and "intelligence_project_unavailable" in resp.text, (path, resp.text)
        patched = client.patch(
            f"/v1/platform/developer/projects/{project_id}", headers=A.jwt, json={"status": "active"}
        )
        assert patched.status_code in (403, 404), patched.text
        db = Session()
        try:
            assert db.get(ApiProject, project_id).status == "suspended"
            assert (
                db.query(PlatformApiKey)
                .filter_by(api_project_id=project_id, status="active")
                .filter(PlatformApiKey.revoked_at.is_(None))
                .count()
                >= 1
            ), "suspension must hold even while keys remain active"
        finally:
            db.close()
        reject(a_key, ask, 401)
        assert len(model_calls) == calls_before
    finally:
        app.dependency_overrides.pop(get_db, None)
        _cleanup(Session, [A.org_id, B.org_id], [A.user_id, B.user_id])
        engine.dispose()

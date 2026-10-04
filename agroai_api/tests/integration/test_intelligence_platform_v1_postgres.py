"""AGRO-AI Intelligence Platform v1 — end-to-end on real PostgreSQL.

Every scenario goes through the real FastAPI application, real advisory key
verification, the credential guard and the hardened money path. The model and
the image analyser are scripted; everything else (tenancy, retrieval, tools,
sessions, jobs, billing) is production code against PostgreSQL.

Invariants proven here:
* a rejected request never reaches the model and never moves money;
* a degraded run (model, attachment, structured output) is never charged;
* each completed run is charged exactly once, at its quoted price;
* every platform resource is invisible across tenants (404, no oracle);
* async jobs are claimed once, retried boundedly, cancellable without charge,
  and stop if the key that created them is revoked.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is required")

FLAGS_ON = ("PLATFORM_API_ENABLED", "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED")


def _tenant(Session, *, balance_cents: int):
    from app.core.security import create_access_token
    from app.models.intelligence_commerce import IntelligenceWallet
    from app.models.saas import Organization, OrganizationMembership, User

    db = Session()
    try:
        s = uuid.uuid4().hex[:10]
        user = User(email=f"intel-platform-{s}@example.com", password_hash="x",
                    email_verification_status="verified", email_verified_at=datetime.utcnow())
        db.add(user)
        db.flush()
        org = Organization(name=f"Intel platform {s}", slug=f"intel-platform-{s}", owner_user_id=user.id,
                           plan="enterprise", subscription_status="active", verification_status="approved")
        db.add(org)
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.add(IntelligenceWallet(organization_id=org.id, currency="usd", balance_cents=balance_cents,
                                  lifetime_funded_cents=balance_cents, lifetime_spent_cents=0))
        db.commit()
        return SimpleNamespace(org_id=org.id, user_id=user.id,
                               jwt={"Authorization": f"Bearer {create_access_token({'sub': user.id})}"})
    finally:
        db.close()


def _wallet(Session, org_id):
    from app.models.intelligence_commerce import IntelligenceWallet, IntelligenceWalletLedger

    db = Session()
    try:
        wallet = db.query(IntelligenceWallet).filter_by(organization_id=org_id).one()
        charges = db.query(IntelligenceWalletLedger).filter_by(organization_id=org_id, kind="intelligence_charge").count()
        return int(wallet.balance_cents), charges
    finally:
        db.close()


def _cleanup(Session, org_ids, user_ids):
    from app.models.intelligence_commerce import CommercialIntelligenceRun, IntelligenceWallet, IntelligenceWalletLedger
    from app.models.intelligence_platform import (
        IntelligenceFile, IntelligenceSession, IntelligenceSessionTurn, KnowledgeChunk, KnowledgeDocument,
    )
    from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
    from app.models.saas import Organization, OrganizationMembership, User, Workspace

    db = Session()
    try:
        for model in (KnowledgeChunk, KnowledgeDocument, IntelligenceSessionTurn, IntelligenceSession, IntelligenceFile,
                      IntelligenceWalletLedger, CommercialIntelligenceRun, IntelligenceWallet, PlatformApiKey,
                      ApiServiceAccount, ApiProject, OrganizationMembership, Workspace):
            db.query(model).filter(model.organization_id.in_(org_ids)).delete(synchronize_session=False)
        db.query(Organization).filter(Organization.id.in_(org_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


class FakeStore:
    """In-memory stand-in for the R2/S3 store with the same tenant checks."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str, str]] = {}
        self.pending: set[str] = set()

    def put_path(self, path, *, tenant_id, connection_id, filename, content_type, expected_sha256, expected_size, pending_registration=False):
        data = open(path, "rb").read()
        assert len(data) == expected_size
        uri = f"s3://fake/agroai/{tenant_id}/{connection_id}/{uuid.uuid4().hex}"
        self.objects[uri] = (data, tenant_id, connection_id)
        if pending_registration:
            self.pending.add(uri)
        return SimpleNamespace(uri=uri)

    def promote(self, uri, *, tenant_id, connection_id):
        self.pending.discard(uri)

    def read_bytes(self, uri, *, max_bytes, tenant_id, connection_id):
        data, owner, namespace = self.objects[uri]
        if owner != tenant_id or namespace != connection_id:
            raise RuntimeError("connector object tenant metadata mismatch")
        return data

    def delete(self, uri, *, tenant_id, connection_id):
        self.objects.pop(uri, None)


@pytest.fixture()
def platform(monkeypatch):
    from app.api.v1 import commercial_intelligence as legacy
    from app.core.config import settings
    from app.db.base import get_db
    from app.intelligence_platform import files as platform_files
    from app.intelligence_platform import runtime as platform_runtime
    from app.main import app

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for name in FLAGS_ON:
        monkeypatch.setattr(settings, name, True, raising=False)
    monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_BACKEND", "disabled", raising=False)

    state = SimpleNamespace(model_calls=[], json_replies=[], json_calls=[], vision_ok=True, model_raises=False)

    async def model(**kwargs):
        state.model_calls.append(kwargs)
        if state.model_raises:
            raise RuntimeError("provider exploded")
        return (
            {"answer": "Scout the north block; evidence [ctx_obs_1] shows stress.", "confidence": "medium"},
            SimpleNamespace(status="ok", demo_fallback=False, provider="internal-vendor", model="internal-model"),
        )

    async def generate_json(messages):
        state.json_calls.append(messages)
        if not state.json_replies:
            return "", None
        return state.json_replies.pop(0), "internal-model"

    def analyze(principal, row, question, crop, language):
        if not state.vision_ok:
            raise RuntimeError("vision down")
        data = platform_files.read_image_bytes(principal, row)
        return {"summary": f"leaf spotting visible ({len(data)} bytes)", "hypotheses": [], "confidence": 0.4}

    store = FakeStore()
    monkeypatch.setattr(legacy, "_run_ai", model)
    monkeypatch.setattr(platform_runtime, "generate_json", generate_json)
    monkeypatch.setattr(platform_runtime, "_analyze_image", analyze)
    monkeypatch.setattr(platform_files, "_object_store", lambda: store)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    A = _tenant(Session, balance_cents=500)
    B = _tenant(Session, balance_cents=500)
    keys = {}
    for name, tenant in (("A", A), ("B", B)):
        boot = client.post("/v1/platform/developer/intelligence/bootstrap", headers=tenant.jwt, json={})
        assert boot.status_code == 200, boot.text
        keys[name] = {"Authorization": f"Bearer {boot.json()['key']['secret']}"}
        tenant.project_id = boot.json()["project"]["id"]
    try:
        yield SimpleNamespace(client=client, Session=Session, A=A, B=B, keys=keys, state=state, store=store)
    finally:
        app.dependency_overrides.pop(get_db, None)
        _cleanup(Session, [A.org_id, B.org_id], [A.user_id, B.user_id])


def _idem():
    return {"Idempotency-Key": uuid.uuid4().hex}


def _run(p, key, body, headers=None):
    return p.client.post("/v1/intelligence", headers={**p.keys[key], **_idem(), **(headers or {})}, json=body)


def test_legacy_request_is_unchanged_and_hash_compatible(platform):
    from app.api.v1 import commercial_intelligence as legacy
    import hashlib

    p = platform
    body = {"task": "answer", "question": "What needs attention?", "input": {"crop": "almond"}}
    resp = _run(p, "A", body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in ("id", "object", "model", "status", "task", "decision", "output", "confidence", "evidence", "billing"):
        assert key in data
    assert data["status"] == "completed" and data["model"] == "agroai-intelligence-1"
    assert data["billing"]["charged_cents"] == 5
    assert data["structured_output_status"] == "not_requested"
    assert "internal-vendor" not in resp.text and "internal-model" not in resp.text
    assert "AGROAI_DATA" not in p.state.model_calls[-1]["user_instruction"], "legacy prompts must not change"
    # Pre-platform hash formula is preserved for legacy-shaped requests.
    payload = legacy.IntelligenceRequest(**body)
    old = hashlib.sha256(json.dumps(
        {"task": "answer", "question": "What needs attention?", "input": {"crop": "almond"},
         "field_id": None, "workspace_id": None, "language": None}, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert legacy._request_hash(payload) == old
    assert _wallet(p.Session, p.A.org_id) == (495, 1)


def test_structured_output_valid_scrubs_fake_citations_and_charges_once(platform):
    p = platform
    p.state.json_replies = [json.dumps({"agroai_structured_output": {
        "summary": "Likely early water stress",
        "likely_causes": [{"name": "water stress", "likelihood": "medium", "reasoning": "low VWC",
                            "evidence_ids": ["ctx_obs_1", "made-up-id"]}],
        "recommended_next_steps": ["Check emitters"], "confidence": "medium", "unexpected": "pruned"}})]
    body = {
        "task": "field_diagnosis", "question": "Why are leaves curling?",
        "context": {"crop": {"name": "almond", "growth_stage": "hull split"},
                    "observations": [{"type": "soil_vwc", "value": 0.12, "unit": "m3/m3", "observed_at": "2026-10-01T08:00:00Z"}]},
        "response_format": {"type": "agroai_schema", "name": "diagnosis"},
    }
    resp = _run(p, "A", body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["structured_output_status"] == "valid"
    assert data["structured_output"]["likely_causes"][0]["evidence_ids"] == ["ctx_obs_1"]
    assert "unexpected" not in data["structured_output"]
    assert data["provenance"]["removed_unverifiable_citations"] == ["made-up-id"]
    assert any(source["id"] == "ctx_obs_1" and source["origin"] == "customer_request" for source in data["provenance"]["sources"])
    assert "AGROAI_DATA" in p.state.model_calls[-1]["user_instruction"]
    assert _wallet(p.Session, p.A.org_id) == (485, 1)


def test_invalid_structured_output_is_degraded_and_never_charged(platform):
    p = platform
    p.state.json_replies = ['{"agroai_structured_output": {"overall_risk": "catastrophic"}}', "not json at all"]
    resp = _run(p, "A", {"task": "crop_risk", "question": "Frost risk?", "response_format": {"type": "agroai_schema", "name": "risk_assessment"}})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["structured_output"] is None and data["structured_output_status"] == "invalid"
    assert data["billing"]["charged_cents"] == 0
    assert len(p.state.json_calls) == 2, "exactly one repair attempt"
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def test_rejections_never_reach_model_or_move_money(platform):
    p = platform
    cases = [
        ({"task": "answer", "question": "x?", "response_format": {"type": "json_schema", "schema": {"type": "object", "properties": {"a": {"type": "string", "pattern": "(a+)+$"}}}}}, 422),
        ({"task": "answer", "question": "x?", "response_format": {"type": "json_schema", "schema": {"type": "object", "$ref": "https://evil.example/schema"}}}, 422),
        ({"task": "answer", "question": "x?", "response_format": {"type": "agroai_schema", "name": "nope"}}, 422),
        ({"task": "answer", "question": "x?", "tools": [{"name": "valves.open.v1", "arguments": {}}]}, 422),
        ({"task": "answer", "question": "x?", "tools": [{"name": "finance.crop_margin.v1", "arguments": {"area_ha": -1}}]}, 422),
        ({"task": "answer", "question": "x?", "context": {"extensions": {"acme.erp": {"api_token": "abcdefghijklmnopqrstu"}}}}, 422),
        ({"task": "answer", "question": "x?", "context": {"unknown_section": {}}}, 422),
        ({"task": "answer", "question": "x?", "context": {"location": {"latitude": 123}}}, 422),
        ({"task": "answer", "question": "x?", "session_id": "ses_" + "0" * 32}, 404),
        ({"task": "answer", "question": "x?", "attachments": [{"file_id": "file_" + "0" * 32}]}, 404),
        ({"task": "answer", "question": "x?", "metadata": {f"k{i}": "v" for i in range(17)}}, 422),
    ]
    deep: dict = {"v": 1}
    for _ in range(40):
        deep = {"n": deep}
    cases.append(({"task": "answer", "question": "x?", "context": {"extensions": {"acme.deep": deep}}}, 422))
    for body, expected in cases:
        before = len(p.state.model_calls)
        resp = _run(p, "A", body)
        assert resp.status_code == expected, (body, resp.status_code, resp.text)
        assert len(p.state.model_calls) == before
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def test_tools_compute_deterministically_with_provenance(platform):
    p = platform
    args = {"area_ha": 10, "expected_yield_per_ha": 3.0, "price_per_unit": 2000, "currency": "USD",
            "costs": [{"category": "water", "amount": 300, "basis": "per_ha"}, {"category": "harvest", "amount": 12000}]}
    direct = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"], json={"name": "finance.crop_margin.v1", "arguments": args})
    assert direct.status_code == 200, direct.text
    out = direct.json()["output"]
    assert out["revenue"] == 60000 and out["total_costs"] == 15000 and out["margin"] == 45000
    assert out["breakeven_price_per_unit"] == 500
    sci = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"], json={"name": "fao56.etc.single_kc.v1", "arguments": {"eto_mm": 6.0, "kc": 1.1}})
    assert sci.status_code == 200 and sci.json()["status"] == "completed", sci.text
    missing = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"], json={"name": "fao56.etc.single_kc.v1", "arguments": {"eto_mm": 6.0}})
    assert missing.status_code == 422  # schema requires kc: fail closed before execution
    listed = p.client.get("/v1/intelligence/tools").json()["data"]
    assert all(tool["side_effects"] == "none" and tool["physical_action"] is False for tool in listed)

    resp = _run(p, "A", {"task": "decision", "question": "Is this block profitable?", "tools": [{"name": "finance.crop_margin.v1", "arguments": args}]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provenance"]["tools"][0]["name"] == "finance.crop_margin.v1"
    assert data["provenance"]["tools"][0]["status"] == "completed"
    assert "45000" in p.state.model_calls[-1]["user_instruction"]
    from app.models.intelligence_commerce import CommercialIntelligenceRun

    db = p.Session()
    try:
        audit = db.get(CommercialIntelligenceRun, data["id"]).tool_calls_json
        assert audit[0]["name"] == "finance.crop_margin.v1" and "arguments_sha256" in audit[0]
        assert "output" not in audit[0], "audit stores no customer values"
    finally:
        db.close()


def test_knowledge_is_tenant_isolated_cited_and_deletable(platform):
    p = platform
    doc = {"collection": "agronomy-notes", "title": "Block 7 scouting", "external_id": "scout-7",
           "text": "Block 7 almonds showed navel orangeworm damage near the north edge. Hull split began on 2026-07-20.",
           "observed_at": "2026-07-21T00:00:00Z", "source": {"type": "scouting_report", "label": "Field scout"}}
    created = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json=doc)
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    unchanged = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json=doc)
    assert unchanged.status_code == 200 and unchanged.json()["id"] == doc_id
    secret = {**doc, "external_id": "leak", "text": "notes Bearer abcdefghijklmnopqrstuvwxyz0123456789"}
    assert p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json=secret).status_code == 422

    hits = p.client.post("/v1/intelligence/knowledge/search", headers=p.keys["A"],
                         json={"collections": ["agronomy-notes"], "query": "orangeworm damage in almonds"}).json()["data"]
    assert hits and hits[0]["document_id"] == doc_id and hits[0]["source"]["label"] == "Field scout"
    foreign = p.client.post("/v1/intelligence/knowledge/search", headers=p.keys["B"],
                            json={"collections": ["agronomy-notes"], "query": "orangeworm damage"}).json()["data"]
    assert foreign == []
    # Each isolation layer holds on its own: the ranked SQL candidates for
    # tenant B exclude A's chunks before the document join re-checks ownership.
    from app.intelligence_platform import knowledge
    from app.platform_api.principal import PlatformPrincipal

    db = p.Session()
    try:
        b_principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id=p.B.org_id,
                                        api_project_id=p.B.project_id, scopes=frozenset({"intelligence:run"}),
                                        environment="live", request_id="iso")
        assert knowledge.candidate_chunks(db, b_principal, collections=["agronomy-notes"], query="orangeworm damage", max_results=5) == []
    finally:
        db.close()
    assert p.client.get(f"/v1/intelligence/knowledge/documents/{doc_id}", headers=p.keys["B"]).status_code == 404
    assert p.client.delete(f"/v1/intelligence/knowledge/documents/{doc_id}", headers=p.keys["B"]).status_code == 404

    resp = _run(p, "A", {"task": "answer", "question": "What pest pressure did scouting find?",
                         "knowledge": {"collections": ["agronomy-notes"]}})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["billing"]["charged_cents"] == 6  # 5 + 1 retrieval
    assert any(s["type"] == "knowledge" and s["document_id"] == doc_id for s in data["provenance"]["sources"])
    assert hits[0]["id"] in p.state.model_calls[-1]["user_instruction"]

    assert p.client.delete(f"/v1/intelligence/knowledge/documents/{doc_id}", headers=p.keys["A"]).status_code == 204
    after = p.client.post("/v1/intelligence/knowledge/search", headers=p.keys["A"],
                          json={"collections": ["agronomy-notes"], "query": "orangeworm"}).json()["data"]
    assert after == []


def test_files_are_sniffed_bounded_and_tenant_scoped(platform):
    p = platform
    up = lambda key, name, data, ctype, purpose="attachment": p.client.post(
        "/v1/intelligence/files", headers=p.keys[key], files={"file": (name, io.BytesIO(data), ctype)}, data={"purpose": purpose})
    text = up("A", "lab.csv", b"sample,nitrate_ppm\nB7,42\n", "text/csv")
    assert text.status_code == 201, text.text
    file_id = text.json()["id"]
    assert up("A", "x.png", b"plain text pretending to be png", "image/png").status_code == 415
    assert up("A", "x.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "application/pdf").status_code == 415
    assert up("A", "x.exe", b"MZ\x90\x00binary", "application/octet-stream").status_code == 415
    assert up("A", "big.txt", b"a" * (2 * 1024 * 1024 + 10), "text/plain").status_code == 413
    pem_header = b"-----BEGIN RSA " + b"PRIVATE KEY-----"  # assembled so repository secret scanning stays clean
    assert up("A", "key.txt", pem_header + b"\nabc\n", "text/plain").status_code == 422
    image = up("A", "leaf.jpg", b"\xff\xd8\xff\xe0" + b"1" * 2048, "image/jpeg")
    assert image.status_code == 201, image.text

    assert p.client.get(f"/v1/intelligence/files/{file_id}", headers=p.keys["B"]).status_code == 404
    before = len(p.state.model_calls)
    stolen = _run(p, "B", {"task": "answer", "question": "Read it", "attachments": [{"file_id": file_id}]})
    assert stolen.status_code == 404 and len(p.state.model_calls) == before

    resp = _run(p, "A", {"task": "field_diagnosis", "question": "Interpret lab and photo",
                         "attachments": [{"file_id": file_id}, {"file_id": image.json()["id"]}]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["billing"]["charged_cents"] == 15 + 2 + 5
    assert "nitrate_ppm" in p.state.model_calls[-1]["user_instruction"]
    assert "leaf spotting visible" in p.state.model_calls[-1]["user_instruction"]

    # Image analysis outage degrades the run: answered, but never billed.
    p.state.vision_ok = False
    balance_before = _wallet(p.Session, p.A.org_id)
    degraded = _run(p, "A", {"task": "field_diagnosis", "question": "Photo?", "attachments": [{"file_id": image.json()["id"]}]})
    assert degraded.status_code == 200 and degraded.json()["status"] == "degraded"
    assert _wallet(p.Session, p.A.org_id) == balance_before

    assert p.client.delete(f"/v1/intelligence/files/{file_id}", headers=p.keys["A"]).status_code == 204
    assert _run(p, "A", {"task": "answer", "question": "again", "attachments": [{"file_id": file_id}]}).status_code == 404


def test_sessions_carry_bounded_history_and_are_isolated(platform):
    p = platform
    created = p.client.post("/v1/intelligence/sessions", headers=p.keys["A"],
                            json={"title": "Block 7", "context": {"crop": {"name": "almond"}}, "retention_days": 7})
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert p.client.get(f"/v1/intelligence/sessions/{sid}", headers=p.keys["B"]).status_code == 404
    assert _run(p, "B", {"task": "answer", "question": "hijack", "session_id": sid}).status_code == 404

    first = _run(p, "A", {"task": "answer", "question": "First question about irrigation?", "session_id": sid})
    assert first.status_code == 200 and first.json()["session"]["turn_count"] == 2
    assert "almond" in p.state.model_calls[-1]["user_instruction"], "pinned session context reaches inference"
    second = _run(p, "A", {"task": "answer", "question": "And the follow-up?", "session_id": sid})
    assert second.json()["session"]["turn_count"] == 4
    history = p.state.model_calls[-1]["history"]
    assert history[0] == {"role": "user", "content": "First question about irrigation?"}

    turns = p.client.get(f"/v1/intelligence/sessions/{sid}/turns", headers=p.keys["A"]).json()["data"]
    assert len(turns) == 4
    assert p.client.delete(f"/v1/intelligence/sessions/{sid}", headers=p.keys["A"]).status_code == 204
    assert p.client.get(f"/v1/intelligence/sessions/{sid}/turns", headers=p.keys["A"]).status_code == 404
    assert _run(p, "A", {"task": "answer", "question": "after delete", "session_id": sid}).status_code == 404
    from app.models.intelligence_platform import IntelligenceSessionTurn

    db = p.Session()
    try:
        assert db.query(IntelligenceSessionTurn).filter_by(session_id=sid).count() == 0
    finally:
        db.close()


def _execute(p, job_id, org_id):
    from app.intelligence_platform import jobs

    db = p.Session()
    try:
        return asyncio.run(jobs.execute_job(db, run_id=job_id, organization_id=org_id, worker_id="test"))
    finally:
        db.close()


def test_async_jobs_lifecycle_billing_and_isolation(platform):
    p = platform
    headers = {**p.keys["A"], "Idempotency-Key": "job-1"}
    body = {"task": "report", "question": "Season summary", "metadata": {"customer_ref": "r-1"}}
    created = p.client.post("/v1/intelligence/jobs", headers=headers, json=body)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["status"] == "queued" and job["metadata"] == {"customer_ref": "r-1"}
    assert p.client.post("/v1/intelligence/jobs", headers=headers, json=body).json()["id"] == job["id"]
    assert p.client.post("/v1/intelligence/jobs", headers=headers, json={**body, "question": "other"}).status_code == 409
    # Same key on the sync endpoint is a different request (execution differs).
    assert p.client.post("/v1/intelligence", headers=headers, json=body).status_code == 409
    assert p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=p.keys["B"]).status_code == 404
    assert p.client.post(f"/v1/intelligence/jobs/{job['id']}/cancel", headers=p.keys["B"]).status_code == 404
    assert _wallet(p.Session, p.A.org_id) == (500, 0), "enqueue never charges"

    assert _execute(p, job["id"], p.B.org_id) == "succeeded", "foreign tenant delivery is a no-op"
    assert _execute(p, job["id"], p.A.org_id) == "completed"
    assert _execute(p, job["id"], p.A.org_id) == "completed", "duplicate delivery does no work"
    done = p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=p.keys["A"]).json()
    assert done["status"] == "completed" and done["charged"] is True and done["result"]["billing"]["charged_cents"] == 50
    assert _wallet(p.Session, p.A.org_id) == (450, 1)
    from app.models.intelligence_commerce import CommercialIntelligenceRun

    db = p.Session()
    try:
        assert db.get(CommercialIntelligenceRun, job["id"]).request_payload_json is None, "payload purged at terminal state"
    finally:
        db.close()

    # Cancel a queued job: closed without charge, and later delivery does nothing.
    queued = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "cancel me"}).json()
    canceled = p.client.post(f"/v1/intelligence/jobs/{queued['id']}/cancel", headers=p.keys["A"])
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
    assert p.client.post(f"/v1/intelligence/jobs/{queued['id']}/cancel", headers=p.keys["A"]).status_code == 409
    calls = len(p.state.model_calls)
    assert _execute(p, queued["id"], p.A.org_id) == "canceled"
    assert len(p.state.model_calls) == calls

    # Transient failures retry with backoff, then fail; never charged.
    p.state.model_raises = True
    flaky = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "flaky"}).json()
    for attempt in range(1, 4):
        db = p.Session()
        try:
            row = db.get(CommercialIntelligenceRun, flaky["id"])
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()
        status = _execute(p, flaky["id"], p.A.org_id)
        assert status == ("queued" if attempt < 3 else "failed"), (attempt, status)
    p.state.model_raises = False
    assert _wallet(p.Session, p.A.org_id) == (450, 1)


def test_job_stops_when_key_revoked_after_enqueue(platform):
    p = platform
    from app.models.platform_api import PlatformApiKey

    job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "queue probe"}).json()
    db = p.Session()
    try:
        for key in db.query(PlatformApiKey).filter_by(organization_id=p.A.org_id).all():
            key.status = "revoked"
            key.revoked_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
    calls = len(p.state.model_calls)
    assert _execute(p, job["id"], p.A.org_id) == "failed"
    assert len(p.state.model_calls) == calls
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def test_job_lease_timeout_is_not_charged(platform):
    p = platform
    from app.intelligence_platform import jobs
    from app.models.intelligence_commerce import CommercialIntelligenceRun

    job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "queue probe"}).json()
    db = p.Session()
    try:
        row = db.get(CommercialIntelligenceRun, job["id"])
        row.status = "processing"
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        assert jobs.sweep(db)["timed_out"] >= 1
    finally:
        db.close()
    assert p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=p.keys["A"]).json()["status"] == "timeout"
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def test_streaming_emits_stage_events_and_bills_once(platform):
    p = platform
    with p.client.stream("POST", "/v1/intelligence", headers={**p.keys["A"], "Idempotency-Key": "stream-1"},
                         json={"task": "answer", "question": "Stream it", "stream": True}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(resp.iter_text())
    events = [line[len("event: "):] for line in raw.splitlines() if line.startswith("event: ")]
    assert events[0] == "run.created" and events[-1] == "run.completed"
    assert "context.ready" in events and "inference.started" in events
    final = json.loads([line for line in raw.splitlines() if line.startswith("data: ")][-1][6:])
    assert final["billing"]["charged_cents"] == 5
    assert _wallet(p.Session, p.A.org_id) == (495, 1)
    # Replay of the same key (non-streamed) returns the stored result, no new charge.
    replay = p.client.post("/v1/intelligence", headers={**p.keys["A"], "Idempotency-Key": "stream-1"},
                           json={"task": "answer", "question": "Stream it"})
    assert replay.status_code == 200 and replay.json()["id"] == final["id"]
    assert _wallet(p.Session, p.A.org_id) == (495, 1)
    run = p.client.get(f"/v1/intelligence/runs/{final['id']}", headers=p.keys["A"])
    assert run.status_code == 200 and run.json()["result"]["id"] == final["id"]
    assert p.client.get(f"/v1/intelligence/runs/{final['id']}", headers=p.keys["B"]).status_code == 404
    # Rejections keep real HTTP statuses even when streaming was requested.
    assert _run(p, "A", {"task": "answer", "question": "stream probe", "stream": True, "session_id": "ses_missing"}).status_code == 404


def test_concurrent_platform_runs_never_overdraw(platform):
    """Balance 500 covers exactly 4 knowledge-grounded reports (51 + 51 + ...)."""
    from concurrent.futures import ThreadPoolExecutor

    p = platform
    db = p.Session()
    try:
        from app.models.intelligence_commerce import IntelligenceWallet

        wallet = db.query(IntelligenceWallet).filter_by(organization_id=p.A.org_id).one()
        wallet.balance_cents = 204  # 4 x (50 report + 1 retrieval)
        db.commit()
    finally:
        db.close()
    p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"],
                  json={"collection": "c", "title": "t", "text": "drip irrigation schedule notes"})
    body = {"task": "report", "question": "drip irrigation report", "knowledge": {"collections": ["c"]}}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _run(p, "A", body).status_code, range(8)))
    balance, charges = _wallet(p.Session, p.A.org_id)
    assert charges == results.count(200) <= 4
    assert balance == 204 - 51 * charges and balance >= 0
    assert set(results) <= {200, 402}


def test_usage_and_capabilities(platform):
    p = platform
    _run(p, "A", {"task": "answer", "question": "usage probe"})
    usage = p.client.get("/v1/intelligence/usage", headers=p.keys["A"]).json()
    assert usage["totals"]["completed"] >= 1 and usage["totals"]["charged_cents"] >= 5
    assert p.client.get("/v1/intelligence/usage", headers=p.keys["B"]).json()["totals"]["runs"] == 0
    caps = p.client.get("/v1/intelligence/capabilities").json()
    assert caps["model"] == "agroai-intelligence-1" and caps["physical_execution"] is False
    assert caps["modalities"]["remote_urls"] is False
    console = p.client.get("/v1/platform/developer/intelligence/usage", headers=p.A.jwt)
    assert console.status_code == 200 and console.json()["totals"]["runs"] >= 1


def test_job_whose_session_was_deleted_fails_without_charge(platform):
    p = platform
    sid = p.client.post("/v1/intelligence/sessions", headers=p.keys["A"], json={"title": "temp"}).json()["id"]
    job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()},
                        json={"task": "answer", "question": "uses session", "session_id": sid}).json()
    assert p.client.delete(f"/v1/intelligence/sessions/{sid}", headers=p.keys["A"]).status_code == 204
    calls = len(p.state.model_calls)
    assert _execute(p, job["id"], p.A.org_id) == "failed"
    assert len(p.state.model_calls) == calls
    detail = p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=p.keys["A"]).json()
    assert detail["status"] == "failed" and detail["error"]["code"] == "session_not_found"
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def _workspace_key(p, tenant, name):
    from app.models.platform_api import ApiProject, ApiServiceAccount
    from app.models.saas import Workspace
    from app.platform_api.keys import create_platform_key

    db = p.Session()
    try:
        workspace = Workspace(organization_id=tenant.org_id, name=name, mode="evaluation")
        db.add(workspace)
        db.flush()
        project = db.get(ApiProject, tenant.project_id)
        account = db.query(ApiServiceAccount).filter_by(api_project_id=tenant.project_id).first()
        _key, secret = create_platform_key(db, project=project, service_account=account, name=name,
                                           scopes=["intelligence:run"], created_by_user_id=tenant.user_id, workspace_id=workspace.id)
        db.commit()
        return {"Authorization": f"Bearer {secret}"}
    finally:
        db.close()


def test_workspace_restricted_keys_cannot_reach_each_others_resources(platform):
    p = platform
    w1, w2 = _workspace_key(p, p.A, "north"), _workspace_key(p, p.A, "south")
    sid = p.client.post("/v1/intelligence/sessions", headers=w1, json={"title": "north"}).json()["id"]
    fid = p.client.post("/v1/intelligence/files", headers=w1, files={"file": ("n.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}).json()["id"]
    doc = p.client.post("/v1/intelligence/knowledge/documents", headers=w1,
                        json={"collection": "notes", "title": "North notes", "external_id": "x", "text": "north block nematode counts"}).json()["id"]
    project_doc = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"],
                                json={"collection": "notes", "title": "Project notes", "external_id": "x", "text": "project-wide nematode policy"}).json()["id"]
    assert project_doc != doc, "same external_id is independent per workspace scope"

    for path in (f"/v1/intelligence/sessions/{sid}", f"/v1/intelligence/files/{fid}", f"/v1/intelligence/knowledge/documents/{doc}"):
        assert p.client.get(path, headers=w2).status_code == 404, path
        assert p.client.get(path, headers=w1).status_code == 200, path
        assert p.client.get(path, headers=p.keys["A"]).status_code == 200, "project-wide key sees the project"
    assert p.client.get(f"/v1/intelligence/knowledge/documents/{project_doc}", headers=w1).status_code == 404
    south = p.client.post("/v1/intelligence/knowledge/search", headers=w2, json={"collections": ["notes"], "query": "nematode"}).json()["data"]
    north = p.client.post("/v1/intelligence/knowledge/search", headers=w1, json={"collections": ["notes"], "query": "nematode"}).json()["data"]
    assert south == [] and [hit["document_id"] for hit in north] == [doc]
    before = len(p.state.model_calls)
    for body in ({"session_id": sid}, {"attachments": [{"file_id": fid}]}):
        assert p.client.post("/v1/intelligence", headers={**w2, **_idem()}, json={"task": "answer", "question": "cross", **body}).status_code == 404
    assert len(p.state.model_calls) == before
    assert p.client.delete(f"/v1/intelligence/sessions/{sid}", headers=w2).status_code == 404
    assert p.client.get("/v1/intelligence/sessions", headers=w2).json()["data"] == []


def test_failed_object_delete_keeps_a_retryable_tombstone(platform):
    p = platform
    from app.intelligence_platform import files as platform_files
    from app.models.intelligence_platform import IntelligenceFile

    image = p.client.post("/v1/intelligence/files", headers=p.keys["A"],
                          files={"file": ("leaf.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 256), "image/png")}).json()
    original_delete = p.store.delete

    def flaky_delete(*args, **kwargs):
        raise RuntimeError("R2 503")

    p.store.delete = flaky_delete
    assert p.client.delete(f"/v1/intelligence/files/{image['id']}", headers=p.keys["A"]).status_code == 204
    assert p.client.get(f"/v1/intelligence/files/{image['id']}", headers=p.keys["A"]).status_code == 404
    db = p.Session()
    try:
        row = db.get(IntelligenceFile, image["id"])
        assert row.status == "deleting" and row.storage_uri in p.store.objects
        p.store.delete = original_delete
        assert platform_files.expire_files(db) >= 1
        db.expire_all()
        row = db.get(IntelligenceFile, image["id"])
        assert row.status == "deleted" and row.storage_uri is None
        assert not p.store.objects, "object removed on retry"
    finally:
        db.close()


def test_failed_sync_run_can_be_retried_with_the_same_key(platform):
    p = platform
    headers = {**p.keys["A"], "Idempotency-Key": "retry-same-key"}
    body = {"task": "answer", "question": "retry me"}
    p.state.model_raises = True
    assert p.client.post("/v1/intelligence", headers=headers, json=body).status_code == 503
    p.state.model_raises = False
    retried = p.client.post("/v1/intelligence", headers=headers, json=body)
    assert retried.status_code == 200 and retried.json()["status"] == "completed", retried.text
    replay = p.client.post("/v1/intelligence", headers=headers, json=body)
    assert replay.json()["id"] == retried.json()["id"]
    assert p.client.post("/v1/intelligence", headers=headers, json={**body, "question": "changed"}).status_code == 409
    assert _wallet(p.Session, p.A.org_id) == (495, 1)


def test_image_upload_uses_pending_registration_and_is_a_live_reference(platform):
    p = platform
    from app.services.field_intelligence import _pending_object_has_live_reference

    image = p.client.post("/v1/intelligence/files", headers=p.keys["A"],
                          files={"file": ("leaf.webp", io.BytesIO(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 64), "image/webp")}).json()
    assert not p.store.pending, "marker cleared after the row committed"
    db = p.Session()
    try:
        from app.models.intelligence_platform import IntelligenceFile

        uri = db.get(IntelligenceFile, image["id"]).storage_uri
        assert _pending_object_has_live_reference(db, uri) is True
        assert _pending_object_has_live_reference(db, uri + "-orphan") is False
    finally:
        db.close()


def test_restricted_key_cannot_read_or_cancel_project_wide_runs(platform):
    p = platform
    restricted = _workspace_key(p, p.A, "east")
    run = _run(p, "A", {"task": "answer", "question": "project-wide run"}).json()
    job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "project job"}).json()
    assert p.client.get(f"/v1/intelligence/runs/{run['id']}", headers=restricted).status_code == 404
    assert p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=restricted).status_code == 404
    assert p.client.post(f"/v1/intelligence/jobs/{job['id']}/cancel", headers=restricted).status_code == 404
    assert p.client.get(f"/v1/intelligence/jobs/{job['id']}", headers=p.keys["A"]).json()["status"] == "queued"


def test_mixed_timezone_window_and_huge_economics_are_422_not_500(platform):
    p = platform
    mixed = _run(p, "A", {"task": "answer", "question": "window", "context": {"time_window": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00"}}})
    assert mixed.status_code == 422, mixed.text
    huge = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                         json={"name": "finance.crop_margin.v1", "arguments": {"area_ha": 1e308, "expected_yield_per_ha": 1e308, "price_per_unit": 1}})
    assert huge.status_code == 422, huge.text


def test_data_tools_match_canonical_project_and_workspace_predicates(platform, monkeypatch):
    p = platform
    from app.intelligence_platform import knowledge
    from app.models.operational_records import EvidenceRecord
    from app.models.saas import ManagedEntity

    db = p.Session()
    try:
        mine = EvidenceRecord(tenant_id=p.A.org_id, evidence_type="soil_vwc", title="mine", summary="s",
                              occurred_at=datetime.utcnow(), value_json={"value": 0.2}, quality_status="usable", citation_label="probe",
                              metadata_json={"platform_api_project_id": p.A.project_id})
        other = EvidenceRecord(tenant_id=p.A.org_id, evidence_type="soil_vwc", title="other project", summary="s",
                               occurred_at=datetime.utcnow(), value_json={"value": 0.9}, quality_status="usable", citation_label="probe",
                               metadata_json={"platform_api_project_id": "another-project"})
        field = ManagedEntity(organization_id=p.A.org_id, workspace_id=None, entity_type="platform_field",
                              display_name="Project field", status="active", metadata_json={"api_project_id": p.A.project_id, "crop": "almond"})
        untagged = ManagedEntity(organization_id=p.A.org_id, workspace_id=None, entity_type="platform_field",
                                 display_name="Legacy untagged", status="active", metadata_json={"crop": "walnut"})
        db.add_all([mine, other, field, untagged])
        db.commit()
        mine_id, other_id, field_id, untagged_id = mine.id, other.id, field.id, untagged.id
    finally:
        db.close()
    try:
        out = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                            json={"name": "observations.query.v1", "arguments": {"limit": 50}}).json()["output"]["observations"]
        ids = {item["id"] for item in out}
        assert mine_id in ids and other_id not in ids, "other API projects' observations never leak"

        restricted = _workspace_key(p, p.A, "west")
        hidden = p.client.post("/v1/intelligence/tools/execute", headers=restricted,
                               json={"name": "fields.get.v1", "arguments": {"field_id": field_id}}).json()
        assert hidden["status"] == "not_found" and hidden["output"] == {}
        visible = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                                json={"name": "fields.get.v1", "arguments": {"field_id": field_id}}).json()
        assert visible["status"] == "completed" and visible["output"]["crop"] == "almond"
        legacy_field = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                                     json={"name": "fields.get.v1", "arguments": {"field_id": untagged_id}}).json()
        assert legacy_field["status"] == "not_found", "untagged legacy entities are not visible to any API project"

        # Knowledge quota is per project, not per workspace.
        monkeypatch.setattr(knowledge, "MAX_DOCUMENTS_PER_PROJECT", 1)
        w1, w2 = _workspace_key(p, p.A, "q1"), _workspace_key(p, p.A, "q2")
        assert p.client.post("/v1/intelligence/knowledge/documents", headers=w1, json={"collection": "c", "title": "a", "text": "alpha"}).status_code == 201
        blocked = p.client.post("/v1/intelligence/knowledge/documents", headers=w2, json={"collection": "c", "title": "b", "text": "beta"})
        assert blocked.status_code == 409 and "quota" in blocked.text
    finally:
        db = p.Session()
        try:
            db.query(EvidenceRecord).filter(EvidenceRecord.id.in_([mine_id, other_id])).delete(synchronize_session=False)
            db.query(ManagedEntity).filter(ManagedEntity.id.in_([field_id, untagged_id])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_review_round_three_regressions(platform):
    p = platform
    from app.models.intelligence_commerce import CommercialIntelligenceRun

    # Re-ingest with a corrected title rebuilds the searchable chunks.
    base = {"collection": "sops", "title": "Old title", "external_id": "sop-1", "text": "flush drip filters weekly"}
    doc = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json=base).json()
    renamed = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json={**base, "title": "Filtration SOP"})
    assert renamed.status_code == 201 and renamed.json()["id"] == doc["id"]
    hits = p.client.post("/v1/intelligence/knowledge/search", headers=p.keys["A"], json={"collections": ["sops"], "query": "filtration"}).json()["data"]
    assert hits and hits[0]["title"] == "Filtration SOP"
    assert p.client.post("/v1/intelligence/knowledge/search", headers=p.keys["A"], json={"collections": ["sops"], "query": "old title"}).json()["data"] == []

    # Knowledge tool hits are resolvable provenance sources.
    run = _run(p, "A", {"task": "answer", "question": "filters?", "tools": [{"name": "knowledge.search.v1", "arguments": {"collections": ["sops"], "query": "filters"}}]}).json()
    assert any(s["type"] == "knowledge" and s.get("via_tool") == "tool_1" and s["document_id"] == doc["id"] for s in run["provenance"]["sources"])

    # A reclaimed old failed run gets a fresh staleness window.
    headers = {**p.keys["A"], "Idempotency-Key": "old-failed"}
    body = {"task": "answer", "question": "old failure"}
    p.state.model_raises = True
    assert p.client.post("/v1/intelligence", headers=headers, json=body).status_code == 503
    p.state.model_raises = False
    db = p.Session()
    try:
        row = db.query(CommercialIntelligenceRun).filter_by(idempotency_key="old-failed").one()
        row.created_at = datetime.utcnow() - timedelta(hours=2)
        row.started_at = datetime.utcnow() - timedelta(hours=2)
        db.commit()
    finally:
        db.close()
    from app.api.v1 import commercial_intelligence_hardened as hardened

    db = p.Session()
    try:
        row = db.query(CommercialIntelligenceRun).filter_by(idempotency_key="old-failed").one()
        row.status, row.started_at = "processing", datetime.utcnow()
        db.commit()
        assert hardened._recover_if_stale(db, run=row, principal=None) is False, "fresh attempt is not stale"
    finally:
        db.close()


def _pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_closeout_file_contracts_utf8_and_page_limit(platform):
    p = platform
    up = lambda name, data, ctype: p.client.post("/v1/intelligence/files", headers=p.keys["A"], files={"file": (name, io.BytesIO(data), ctype)})
    # Invalid UTF-8 at the very end of a short file passes the 512-byte sniff
    # tolerance but must still be a deterministic 415, never a 500.
    short_tail = up("tail.txt", b"nitrate ok\n\xe2\x82", "text/plain")
    assert short_tail.status_code == 415 and short_tail.json()["detail"]["code"] == "file_text_must_be_utf8", short_tail.text
    # Invalid sequence straddling the sniff boundary (bytes 510-513), in a longer file.
    boundary = b"a" * 510 + b"\xe2\x82" + b"\xff" + b"b" * 100
    straddle = up("edge.csv", boundary, "text/csv")
    assert straddle.status_code == 415 and straddle.json()["detail"]["code"] == "file_text_must_be_utf8", straddle.text
    # Valid multibyte text split across the boundary is accepted.
    assert up("ok.md", b"a" * 511 + "é".encode() + b" fine", "text/markdown").status_code == 201

    ok = up("200.pdf", _pdf(200), "application/pdf")
    assert ok.status_code == 201 and ok.json()["page_count"] == 200, ok.text
    too_many = up("201.pdf", _pdf(201), "application/pdf")
    assert too_many.status_code == 422 and too_many.json()["detail"]["code"] == "document_page_limit_exceeded"
    assert p.client.get("/v1/intelligence/capabilities").json()["modalities"]["documents"]["max_pages"] == 200


def test_closeout_sdk_inferred_text_types_are_accepted_by_server(platform, tmp_path):
    import importlib
    import sys
    from pathlib import Path

    sdk_root = str(Path(__file__).resolve().parents[3] / "sdk" / "python")
    sys.path.insert(0, sdk_root)
    for name in [m for m in sys.modules if m == "agroai" or m.startswith("agroai.")]:
        del sys.modules[name]
    try:
        agroai = importlib.import_module("agroai")
        token = platform.keys["A"]["Authorization"].split(" ", 1)[1]
        client = agroai.AgroAI(api_key=token, base_url="http://testserver", http_client=platform.client, max_retries=0)
        for filename, body in (("notes.txt", b"scouted rows 1-4"), ("lab.csv", b"sample,ppm\nB7,42\n"),
                               ("sop.md", b"# SOP\nflush filters"), ("records.json", b'{"rows": 2}')):
            path = tmp_path / filename
            path.write_bytes(body)
            uploaded = client.intelligence.files.upload(str(path))  # no explicit content type
            assert uploaded.kind == "text", (filename, uploaded)
        unknown = tmp_path / "blob.bin"
        unknown.write_bytes(b"opaque bytes")
        with pytest.raises(agroai.UnsupportedMediaTypeError):
            client.intelligence.files.upload(str(unknown))
    finally:
        sys.path.remove(sdk_root)
        for name in [m for m in sys.modules if m == "agroai" or m.startswith("agroai.")]:
            del sys.modules[name]


def test_closeout_knowledge_reingest_from_new_file_refreshes_source(platform):
    p = platform
    up = lambda name: p.client.post("/v1/intelligence/files", headers=p.keys["A"], data={"purpose": "knowledge"},
                                    files={"file": (name, io.BytesIO(b"drip filter flushing every week"), "text/plain")}).json()["id"]
    first, second = up("v1.txt"), up("v2.txt")
    body = {"collection": "sops", "title": "Filter SOP", "external_id": "filters"}
    doc = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json={**body, "file_id": first}).json()
    assert doc["file_id"] == first
    again = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json={**body, "file_id": second})
    assert again.status_code == 200, "identical text: no re-index"
    assert again.json()["id"] == doc["id"] and again.json()["file_id"] == second
    assert p.client.delete(f"/v1/intelligence/files/{first}", headers=p.keys["A"]).status_code == 204
    current = p.client.get(f"/v1/intelligence/knowledge/documents/{doc['id']}", headers=p.keys["A"]).json()
    assert current["file_id"] == second, "never points at the deleted upload"
    inline = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json={**body, "text": "drip filter flushing every week"})
    assert inline.json()["file_id"] is None, "inline text is the source now"


def test_closeout_time_filters_preserve_the_instant(platform):
    p = platform
    from app.models.intelligence_commerce import CommercialIntelligenceRun
    from app.models.operational_records import EvidenceRecord

    instant = datetime(2026, 10, 3, 12, 0, 0)  # naive UTC, the DB convention
    db = p.Session()
    try:
        before_rec = EvidenceRecord(tenant_id=p.A.org_id, evidence_type="t", title="before", summary="s", citation_label="c",
                                    occurred_at=instant - timedelta(minutes=30), value_json={}, quality_status="usable",
                                    metadata_json={"platform_api_project_id": p.A.project_id})
        after_rec = EvidenceRecord(tenant_id=p.A.org_id, evidence_type="t", title="after", summary="s", citation_label="c",
                                   occurred_at=instant + timedelta(minutes=30), value_json={}, quality_status="usable",
                                   metadata_json={"platform_api_project_id": p.A.project_id})
        db.add_all([before_rec, after_rec])
        db.commit()
        ids = (before_rec.id, after_rec.id)
    finally:
        db.close()
    try:
        # 14:00+02:00 is exactly 12:00Z. Dropping the offset would wrongly mean 14:00Z.
        out = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                            json={"name": "observations.query.v1", "arguments": {"since": "2026-10-03T14:00:00+02:00", "evidence_type": "t"}}).json()
        titles = {item["title"] for item in out["output"]["observations"]}
        assert titles == {"after"}, titles
        out = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"],
                            json={"name": "observations.query.v1", "arguments": {"since": "2026-10-03T06:00:00-06:00", "evidence_type": "t"}}).json()
        assert {item["title"] for item in out["output"]["observations"]} == {"after"}

        run = _run(p, "A", {"task": "answer", "question": "time probe"}).json()
        db = p.Session()
        try:
            row = db.get(CommercialIntelligenceRun, run["id"])
            row.created_at = instant
            db.commit()
        finally:
            db.close()
        listed = lambda before: {r["id"] for r in p.client.get("/v1/intelligence/runs", headers=p.keys["A"], params={"before": before}).json()["data"]}
        assert run["id"] in listed("2026-10-03T14:00:01+02:00"), "12:00:01Z is after the run"
        assert run["id"] not in listed("2026-10-03T13:59:59+02:00"), "11:59:59Z is before the run"

        # Knowledge observed_at keeps the instant too.
        doc = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"],
                            json={"collection": "t", "title": "tz", "text": "tz probe", "observed_at": "2026-10-03T14:00:00+02:00"}).json()
        assert doc["observed_at"].startswith("2026-10-03T12:00:00"), doc["observed_at"]
    finally:
        db = p.Session()
        try:
            db.query(EvidenceRecord).filter(EvidenceRecord.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_data_tool_statement_timeout_bounds_a_stalled_query(platform, monkeypatch):
    p = platform
    import time as _time

    from sqlalchemy import text as sql_text

    from app.intelligence_platform import tools
    from app.intelligence_platform.contract import ToolCall
    from app.platform_api.principal import PlatformPrincipal

    def stalled(ctx, arguments):
        ctx.db.execute(sql_text("SELECT pg_sleep(3)"))
        return {"status": "completed", "output": {}}

    tool = tools.PlatformTool(name="stalled.data.v1", version="1", category="data", description="",
                              input_schema={"type": "object"}, handler=stalled, timeout_ms=200, max_attempts=2)
    monkeypatch.setitem(tools.REGISTRY._tools, tool.name, tool)
    db = p.Session()
    try:
        principal = PlatformPrincipal(authentication_type="platform_api_key", organization_id=p.A.org_id,
                                      api_project_id=p.A.project_id, scopes=frozenset({"intelligence:run"}),
                                      environment="live", request_id="deadline")
        before = db.execute(sql_text("SHOW statement_timeout")).scalar()
        db.commit()
        started = _time.monotonic()
        result = tools.execute(tools.ToolContext(db=db, principal=principal), [ToolCall(name="stalled.data.v1", arguments={})])[0]
        elapsed = _time.monotonic() - started
        assert result["status"] == "timeout" and result["attempts"] == 1, result
        assert elapsed < 1.5, f"stalled query must be cancelled at the deadline ({elapsed:.2f}s)"
        assert db.execute(sql_text("SELECT 1")).scalar() == 1, "session usable afterwards"
        assert db.execute(sql_text("SHOW statement_timeout")).scalar() == before, "timeout is not leaked"
        # A fast data tool restores the previous timeout within the same transaction.
        tools.execute(tools.ToolContext(db=db, principal=principal),
                      [ToolCall(name="observations.query.v1", arguments={})])
        assert db.execute(sql_text("SHOW statement_timeout")).scalar() == before
    finally:
        db.rollback()
        db.close()


def test_knowledge_title_and_metadata_are_credential_scanned(platform):
    p = platform
    token = "gh" + "p_" + "A" * 36  # assembled so repository secret scanning stays clean
    base = {"collection": "c", "title": "Safe title", "text": "irrigation notes"}
    for body in ({**base, "title": f"notes {token}"},
                 {**base, "source": {"type": "doc", "label": f"exported with {token}"}},
                 {**base, "source": {"type": "doc", "uri": f"https://example.test/x?key={token}"}},
                 {**base, "metadata": {"api_token": "abcdefghijklmnopqrstuvwxyz"}}):
        resp = p.client.post("/v1/intelligence/knowledge/documents", headers=p.keys["A"], json=body)
        assert resp.status_code == 422 and "credential_like_input_rejected" in resp.text, (body, resp.text)
    assert p.client.get("/v1/intelligence/knowledge/documents", headers=p.keys["A"]).json()["data"] == []


def test_session_history_sends_exactly_the_latest_eight_turns(platform):
    p = platform
    sid = p.client.post("/v1/intelligence/sessions", headers=p.keys["A"], json={"title": "long"}).json()["id"]
    for index in range(6):  # 12 stored turns
        assert _run(p, "A", {"task": "answer", "question": f"question number {index}", "session_id": sid}).status_code == 200
    _run(p, "A", {"task": "answer", "question": "final question", "session_id": sid})
    history = p.state.model_calls[-1]["history"]
    assert len(history) == 8, len(history)
    assert history[-1]["role"] == "assistant" and history[-2] == {"role": "user", "content": "question number 5"}
    assert {"role": "user", "content": "question number 1"} not in history, "older turns stay out of context"


def test_file_byte_quotas_are_project_wide_and_race_safe(platform, monkeypatch):
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    from app.intelligence_platform import files as platform_files

    p = platform
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 292  # 300 bytes
    monkeypatch.setattr(platform_files, "MAX_OBJECT_BYTES_PER_PROJECT", 1000)  # room for exactly 3
    original_put = p.store.put_path

    def slow_put(*args, **kwargs):
        _time.sleep(0.3)  # every upload passes the early check before any commits
        return original_put(*args, **kwargs)

    p.store.put_path = slow_put
    w1, w2 = _workspace_key(p, p.A, "qa"), _workspace_key(p, p.A, "qb")
    keys = [w1, w2, p.keys["A"]] * 2

    def upload(headers):
        return p.client.post("/v1/intelligence/files", headers=headers, files={"file": ("x.png", io.BytesIO(png), "image/png")}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(upload, keys))
    assert codes.count(201) == 3 and codes.count(409) == 3, codes
    assert len(p.store.objects) == 3, "rejected uploads leave no stored object"

    monkeypatch.setattr(platform_files, "MAX_EXTRACTED_TEXT_CHARS_PER_PROJECT", 30)
    text = lambda: p.client.post("/v1/intelligence/files", headers=p.keys["A"], files={"file": ("n.txt", io.BytesIO(b"x" * 20), "text/plain")})
    assert text().status_code == 201
    second = text()
    assert second.status_code == 409 and second.json()["detail"]["code"] == "file_text_quota_exceeded"


def test_key_resource_allowlists_are_enforced_on_intelligence(platform):
    p = platform
    from app.models.operational_records import EvidenceRecord
    from app.models.platform_api import ApiProject, ApiServiceAccount
    from app.models.saas import ManagedEntity
    from app.platform_api.keys import create_platform_key

    db = p.Session()
    try:
        allowed = ManagedEntity(organization_id=p.A.org_id, workspace_id=None, entity_type="platform_field", display_name="Allowed",
                                status="active", metadata_json={"api_project_id": p.A.project_id, "crop": "almond"})
        blocked = ManagedEntity(organization_id=p.A.org_id, workspace_id=None, entity_type="platform_field", display_name="Blocked",
                                status="active", metadata_json={"api_project_id": p.A.project_id, "crop": "secret-crop"})
        db.add_all([allowed, blocked])
        db.flush()
        records = [
            EvidenceRecord(tenant_id=p.A.org_id, evidence_type="ra", title=title, summary="s", citation_label="c", field_id=fid,
                           occurred_at=datetime.utcnow(), value_json={}, quality_status="usable",
                           metadata_json={"platform_api_project_id": p.A.project_id})
            for title, fid in (("allowed-obs", allowed.id), ("blocked-obs", blocked.id), ("fieldless-obs", None))
        ]
        db.add_all(records)
        project = db.get(ApiProject, p.A.project_id)
        account = db.query(ApiServiceAccount).filter_by(api_project_id=p.A.project_id).first()
        account.resource_restrictions_json = {}
        key, secret = create_platform_key(db, project=project, service_account=account, name="field-limited",
                                          scopes=["intelligence:run"], created_by_user_id=p.A.user_id,
                                          resource_restrictions={"field_ids": [allowed.id]})
        db.commit()
        allowed_id, blocked_id, record_ids = allowed.id, blocked.id, [r.id for r in records]
    finally:
        db.close()
    limited = {"Authorization": f"Bearer {secret}"}
    try:
        tool = lambda name, args: p.client.post("/v1/intelligence/tools/execute", headers=limited, json={"name": name, "arguments": args}).json()
        assert tool("fields.get.v1", {"field_id": allowed_id})["status"] == "completed"
        assert tool("fields.get.v1", {"field_id": blocked_id})["status"] == "not_found"
        titles = {o["title"] for o in tool("observations.query.v1", {"evidence_type": "ra"})["output"]["observations"]}
        assert titles == {"allowed-obs"}, titles
        assert tool("observations.query.v1", {"field_id": blocked_id})["status"] == "not_found"

        before = len(p.state.model_calls)
        denied = p.client.post("/v1/intelligence", headers={**limited, **_idem()}, json={"task": "answer", "question": "blocked field", "field_id": blocked_id})
        assert denied.status_code in {403, 404} and len(p.state.model_calls) == before
        ok = p.client.post("/v1/intelligence", headers={**limited, **_idem()}, json={"task": "answer", "question": "what is recorded?"})
        assert ok.status_code == 200
        sent = json.dumps(p.state.model_calls[-1]["context"].model_dump(mode="json"))
        assert "allowed-obs" in sent and "blocked-obs" not in sent and "fieldless-obs" not in sent
        # Stored runs: a restricted key sees only runs it created itself.
        foreign_run = p.client.post("/v1/intelligence", headers={**p.keys["A"], **_idem()},
                                    json={"task": "answer", "question": "about blocked", "field_id": blocked_id}).json()
        foreign_job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()},
                                    json={"task": "answer", "question": "queued for blocked", "field_id": blocked_id}).json()
        assert p.client.get(f"/v1/intelligence/runs/{foreign_run['id']}", headers=limited).status_code == 404
        assert p.client.get(f"/v1/intelligence/jobs/{foreign_job['id']}", headers=limited).status_code == 404
        assert p.client.post(f"/v1/intelligence/jobs/{foreign_job['id']}/cancel", headers=limited).status_code == 404
        listed = {r["id"] for r in p.client.get("/v1/intelligence/runs", headers=limited, params={"limit": 100}).json()["data"]}
        assert ok.json()["id"] in listed and foreign_run["id"] not in listed and foreign_job["id"] not in listed
        assert foreign_job["id"] not in {j["id"] for j in p.client.get("/v1/intelligence/jobs", headers=limited).json()["data"]}
        assert p.client.get(f"/v1/intelligence/runs/{ok.json()['id']}", headers=limited).status_code == 200
        assert p.client.get(f"/v1/intelligence/runs/{foreign_run['id']}", headers=p.keys["A"]).status_code == 200
        # Sessions: a restricted key cannot read or continue another key's session history.
        shared = p.client.post("/v1/intelligence/sessions", headers=p.keys["A"], json={"title": "project-wide"}).json()["id"]
        assert p.client.get(f"/v1/intelligence/sessions/{shared}", headers=limited).status_code == 404
        assert p.client.get(f"/v1/intelligence/sessions/{shared}/turns", headers=limited).status_code == 404
        assert p.client.post("/v1/intelligence", headers={**limited, **_idem()}, json={"task": "answer", "question": "continue", "session_id": shared}).status_code == 404
        own = p.client.post("/v1/intelligence/sessions", headers=limited, json={"title": "mine"}).json()["id"]
        assert p.client.get(f"/v1/intelligence/sessions/{own}", headers=limited).status_code == 200
        assert shared not in {item["id"] for item in p.client.get("/v1/intelligence/sessions", headers=limited).json()["data"]}
        # Unrestricted project key still sees everything.
        full = p.client.post("/v1/intelligence/tools/execute", headers=p.keys["A"], json={"name": "observations.query.v1", "arguments": {"evidence_type": "ra"}}).json()
        assert {o["title"] for o in full["output"]["observations"]} == {"allowed-obs", "blocked-obs", "fieldless-obs"}
    finally:
        db = p.Session()
        try:
            db.query(EvidenceRecord).filter(EvidenceRecord.id.in_(record_ids)).delete(synchronize_session=False)
            db.query(ManagedEntity).filter(ManagedEntity.id.in_([allowed_id, blocked_id])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_session_quota_is_race_safe(platform, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.intelligence_platform import sessions as platform_sessions

    p = platform
    import time as _time

    monkeypatch.setattr(platform_sessions, "MAX_ACTIVE_SESSIONS_PER_PROJECT", 3)
    real_timedelta = platform_sessions.timedelta

    def slow_timedelta(*args, **kwargs):  # widens the count -> insert window
        _time.sleep(0.2)
        return real_timedelta(*args, **kwargs)

    monkeypatch.setattr(platform_sessions, "timedelta", slow_timedelta)
    # Distinct keys: requests on one key already serialize on its last-used update.
    keys = [_workspace_key(p, p.A, f"s{index}") for index in range(7)] + [p.keys["A"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda headers: p.client.post("/v1/intelligence/sessions", headers=headers, json={"title": "q"}).status_code, keys))
    assert codes.count(201) == 3 and codes.count(409) == 5, codes


def test_run_cursor_never_skips_tied_timestamps(platform):
    p = platform
    from app.models.intelligence_commerce import CommercialIntelligenceRun

    ids = [_run(p, "A", {"task": "answer", "question": f"tie {index}"}).json()["id"] for index in range(4)]
    db = p.Session()
    try:
        tied = datetime(2026, 10, 3, 9, 0, 0)
        for row in db.query(CommercialIntelligenceRun).filter(CommercialIntelligenceRun.id.in_(ids)).all():
            row.created_at = tied
        db.commit()
    finally:
        db.close()
    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 1, **({"before": cursor} if cursor else {})}
        page = p.client.get("/v1/intelligence/runs", headers=p.keys["A"], params=params).json()
        seen.extend(item["id"] for item in page["data"])
        cursor = page["next_before"]
        if not page["has_more"]:
            break
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen)), seen
    assert p.client.get("/v1/intelligence/runs", headers=p.keys["A"], params={"before": "not-a-cursor"}).status_code == 422


def test_run_grounding_never_uses_another_api_projects_evidence(platform):
    p = platform
    from app.models.operational_records import EvidenceRecord

    db = p.Session()
    try:
        rows = [
            EvidenceRecord(tenant_id=p.A.org_id, evidence_type="g", title=title, summary="s", citation_label="c",
                           occurred_at=datetime.utcnow(), value_json={}, quality_status="usable", metadata_json=meta)
            for title, meta in (("this-project-obs", {"platform_api_project_id": p.A.project_id}),
                                ("other-project-obs", {"platform_api_project_id": "another-api-project"}),
                                ("org-portal-obs", {}))
        ]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    finally:
        db.close()
    try:
        assert _run(p, "A", {"task": "answer", "question": "what was observed?"}).status_code == 200
        sent = json.dumps(p.state.model_calls[-1]["context"].model_dump(mode="json"))
        assert "this-project-obs" in sent and "org-portal-obs" in sent
        assert "other-project-obs" not in sent
    finally:
        db = p.Session()
        try:
            db.query(EvidenceRecord).filter(EvidenceRecord.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_every_request_string_is_credential_scanned(platform):
    p = platform
    secret = "sk_" + "live_" + "A1b2C3d4E5f6G7h8"  # assembled so repository secret scanning stays clean
    file_id = p.client.post("/v1/intelligence/files", headers=p.keys["A"],
                            files={"file": ("ok.txt", io.BytesIO(b"plain notes"), "text/plain")}).json()["id"]
    bodies = [
        {"response_format": {"type": "json_schema", "name": secret, "schema": {"type": "object"}}},
        {"response_format": {"type": "json_schema", "name": "x", "description": secret, "schema": {"type": "object"}}},
        {"attachments": [{"file_id": file_id, "label": secret}]},
        {"knowledge": {"collections": ["c"], "query": f"find {secret}"}},
        {"language": secret},
        {"metadata": {"ref": secret}},
    ]
    before = len(p.state.model_calls)
    for extra in bodies:
        resp = _run(p, "A", {"task": "answer", "question": "probe question", **extra})
        assert resp.status_code == 422 and "credential_like_input_rejected" in resp.text, (extra, resp.status_code, resp.text)
        job = p.client.post("/v1/intelligence/jobs", headers={**p.keys["A"], **_idem()}, json={"task": "answer", "question": "probe question", **extra})
        assert job.status_code == 422, (extra, job.text)
    assert len(p.state.model_calls) == before
    upload = p.client.post("/v1/intelligence/files", headers=p.keys["A"],
                           files={"file": (f"{secret}.txt", io.BytesIO(b"plain notes"), "text/plain")})
    assert upload.status_code == 422 and upload.json()["detail"]["field"] == "filename"
    assert p.client.post("/v1/intelligence/sessions", headers=p.keys["A"], json={"title": secret}).status_code == 422
    assert _wallet(p.Session, p.A.org_id) == (500, 0)


def test_workspace_scoped_run_cannot_use_a_project_wide_field(platform):
    p = platform
    from app.models.saas import ManagedEntity

    db = p.Session()
    try:
        field = ManagedEntity(organization_id=p.A.org_id, workspace_id=None, entity_type="platform_field",
                              display_name="Project-wide block", status="active",
                              metadata_json={"api_project_id": p.A.project_id, "crop": "pistachio", "boundary": {"type": "Point", "coordinates": [0, 0]}})
        db.add(field)
        db.commit()
        field_id = field.id
    finally:
        db.close()
    try:
        restricted = _workspace_key(p, p.A, "scoped-runs")
        before = len(p.state.model_calls)
        denied = p.client.post("/v1/intelligence", headers={**restricted, **_idem()}, json={"task": "answer", "question": "field?", "field_id": field_id})
        assert denied.status_code == 404 and len(p.state.model_calls) == before
        job = p.client.post("/v1/intelligence/jobs", headers={**restricted, **_idem()}, json={"task": "answer", "question": "field?", "field_id": field_id})
        assert job.status_code == 404
        ok = _run(p, "A", {"task": "answer", "question": "field?", "field_id": field_id})
        assert ok.status_code == 200 and "pistachio" in json.dumps(p.state.model_calls[-1]["context"].model_dump(mode="json"))
    finally:
        db = p.Session()
        try:
            db.query(ManagedEntity).filter(ManagedEntity.id == field_id).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def test_workspace_scoped_run_by_project_key_uses_only_that_workspaces_resources(platform):
    p = platform
    from app.models.platform_api import PlatformApiKey

    w1, w2 = _workspace_key(p, p.A, "run-w1"), _workspace_key(p, p.A, "run-w2")
    db = p.Session()
    try:
        ws = {k.name: k.workspace_id for k in db.query(PlatformApiKey).filter(
            PlatformApiKey.organization_id == p.A.org_id, PlatformApiKey.name.in_(["run-w1", "run-w2"])).all()}
    finally:
        db.close()
    w2_session = p.client.post("/v1/intelligence/sessions", headers=w2, json={"title": "w2", "context": {"crop": {"name": "w2-secret-crop"}}}).json()["id"]
    w2_file = p.client.post("/v1/intelligence/files", headers=w2, files={"file": ("w2.txt", io.BytesIO(b"w2 confidential notes"), "text/plain")}).json()["id"]
    p.client.post("/v1/intelligence/knowledge/documents", headers=w2, json={"collection": "kb", "title": "W2 doc", "text": "nematode w2-only finding"})
    w1_session = p.client.post("/v1/intelligence/sessions", headers=w1, json={"title": "w1"}).json()["id"]

    before = len(p.state.model_calls)
    run_in_w1 = lambda extra: p.client.post("/v1/intelligence", headers={**p.keys["A"], **_idem()},
                                            json={"task": "answer", "question": "nematode status", "workspace_id": ws["run-w1"], **extra})
    assert run_in_w1({"session_id": w2_session}).status_code == 404
    assert run_in_w1({"attachments": [{"file_id": w2_file}]}).status_code == 404
    assert len(p.state.model_calls) == before
    grounded = run_in_w1({"session_id": w1_session, "knowledge": {"collections": ["kb"]}})
    assert grounded.status_code == 200
    sent = p.state.model_calls[-1]["user_instruction"]
    assert "w2-only finding" not in sent and "w2-secret-crop" not in sent
    # The stored run belongs to W1 and is readable by the W1 key only.
    assert p.client.get(f"/v1/intelligence/runs/{grounded.json()['id']}", headers=w1).status_code == 200
    assert p.client.get(f"/v1/intelligence/runs/{grounded.json()['id']}", headers=w2).status_code == 404

from __future__ import annotations

from datetime import datetime

from app.core.security import create_access_token
from app.models.operational_records import DataSource, EvidenceRecord
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.schemas.ai import ToolCitation
from app.services.citation_verifier import verify_citations
from app.services.intelligence_context import build_intelligence_context


def _seed_auth_context(db):
    user = User(id="user-1", email="owner@example.com", name="Owner", password_hash="x", is_active=True)
    org = Organization(id="org-1", name="Org One", slug="org-one", owner_user_id=user.id, plan="free", subscription_status="inactive")
    membership = OrganizationMembership(id="membership-1", organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(id="ws-1", organization_id=org.id, name="Primary Workspace", crop="almonds", region="CA", mode="evaluation")
    db.add_all([user, org, membership, workspace])
    db.commit()
    return user, org, workspace


def _headers(user_id: str, tenant_id: str) -> dict[str, str]:
    token = create_access_token({"sub": user_id, "tenant_id": tenant_id})
    return {"Authorization": f"Bearer {token}"}


def test_ai_status_works_without_secrets(client, monkeypatch):
    monkeypatch.setattr("app.services.model_router.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_MODEL", "")

    response = client.get("/v1/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["mode"] == "offline"
    assert "AI_API_KEY" not in str(body)


def test_intelligence_context_excludes_secrets_and_oauth_codes(db):
    user, org, workspace = _seed_auth_context(db)
    source = DataSource(
        id="source-1",
        tenant_id=org.id,
        workspace_id=workspace.id,
        source_type="document_email_context",
        provider="gmail",
        filename="ops.csv",
        status="uploaded",
        metadata_json={"api_key": "secret", "oauth_code": "top-secret", "path": "safe"},
    )
    evidence = EvidenceRecord(
        id="evidence-1",
        tenant_id=org.id,
        workspace_id=workspace.id,
        data_source_id=source.id,
        evidence_type="field_context",
        title="Field note",
        summary="Observed irrigation pressure swing.",
        value_json={},
        citation_label="Field note",
        metadata_json={"token": "hidden", "operator_note": "keep"},
        occurred_at=datetime.utcnow(),
    )
    db.add_all([source, evidence])
    db.commit()

    payload = build_intelligence_context(db=db, tenant_id=org.id, user=user, workspace_id=workspace.id)
    serialized = str(payload)

    assert "top-secret" not in serialized
    assert "secret" not in serialized
    assert "hidden" not in serialized
    assert "path" in serialized
    assert "operator_note" in serialized


def test_intelligence_run_returns_structured_fallback(client, db, monkeypatch):
    user, org, workspace = _seed_auth_context(db)
    monkeypatch.setattr("app.services.model_router.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_MODEL", "")

    response = client.post(
        "/v1/intelligence/run",
        json={"task": "chat", "question": "What is missing?", "workspace_id": workspace.id},
        headers=_headers(user.id, org.id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_status"] == "fallback"
    assert body["provider"] == "offline"
    assert body["result"]["summary"]
    assert isinstance(body["missing_data"], list)


def test_citation_verifier_catches_missing_citations():
    verification, result = verify_citations(
        citations=[
            ToolCitation(source_type="evidence", source_id="1", title="Keep", tenant_id="org-1", workspace_id="ws-1"),
            ToolCitation(source_type="evidence", source_id="2", title="Drop", tenant_id="other-org", workspace_id="ws-2"),
        ],
        result={"confidence": "high", "summary": "Grounded output."},
        tenant_id="org-1",
        workspace_id="ws-1",
    )

    assert verification.status == "partial"
    assert len(verification.citations) == 1
    assert result["confidence"] in {"medium", "low"}
    assert verification.risk_flags


def test_report_factory_still_works(client, db, monkeypatch):
    user, org, workspace = _seed_auth_context(db)
    monkeypatch.setattr("app.services.model_router.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_MODEL", "")

    response = client.post(
        "/v1/intelligence/run",
        json={"task": "report_factory", "question": "Draft an executive brief.", "workspace_id": workspace.id, "audience": "owner"},
        headers=_headers(user.id, org.id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["title"]
    assert "missing_evidence" in body["result"]


def test_decision_workbench_still_works(client, db, monkeypatch):
    user, org, workspace = _seed_auth_context(db)
    monkeypatch.setattr("app.services.model_router.settings.AI_PROVIDER", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_BASE_URL", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_API_KEY", "")
    monkeypatch.setattr("app.services.model_router.settings.AI_MODEL", "")

    response = client.post(
        "/v1/intelligence/run",
        json={"task": "decision_workbench", "question": "What should the operator do today?", "workspace_id": workspace.id},
        headers=_headers(user.id, org.id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["summary"]
    assert "missing_evidence" in body["result"]

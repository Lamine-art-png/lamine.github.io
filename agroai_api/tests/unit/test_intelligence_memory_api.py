from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401
from app.api.v1 import intelligence_memory_api as api
from app.db.base import Base
from app.models.operational_records import EvidenceRecord
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket
from app.services.intelligence_memory_service import persist_grounded_decision_memory


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_org(db):
    owner = User(email="owner@example.com", password_hash="x", email_verification_status="verified")
    viewer = User(email="viewer@example.com", password_hash="x", email_verification_status="verified")
    db.add_all([owner, viewer])
    db.flush()
    org = Organization(name="Memory Org", slug="memory-org", owner_user_id=owner.id, plan="professional", subscription_status="active")
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="Field Operations", mode="evaluation")
    db.add(workspace)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner", status="active"))
    db.add(OrganizationMembership(organization_id=org.id, user_id=viewer.id, role="viewer", status="active"))
    db.commit()
    return owner, viewer, org, workspace


def _packet(org, workspace):
    return IntelligenceGroundingPacket(
        generated_at="2026-08-22T20:00:00Z",
        organization_id=org.id,
        workspace_id=workspace.id,
        field_id="field-1",
        observed_facts=[
            EvidenceSignal(
                evidence_id="meter-1",
                source_type="meter_reading",
                classification="observed",
                information_class="OBSERVED",
                title="Flow meter",
                statement="Measured flow is 120 gpm.",
                organization_id=org.id,
                workspace_id=workspace.id,
                field_id="field-1",
                block_id="block-a",
                confidence_score=0.9,
                provenance={"operational_eligible": True},
            )
        ],
        grounding_confidence=0.8,
    )


def _decision():
    return {
        "answer": "Review the operating decision.",
        "recommendations": [
            {
                "action": "Run irrigation",
                "requires_human_approval": True,
                "evidence_ids": ["meter-1"],
                "verification": "Verify the executed operation and field response.",
            }
        ],
    }


def _life(db, owner, org, workspace):
    refs = persist_grounded_decision_memory(
        db,
        _packet(org, workspace),
        _decision(),
        request_id="request-api",
        task="irrigation_decision",
        question="What should I do?",
        user_id=owner.id,
        model_provider="openai",
        model_name="gpt-5.6-sol",
        reasoning_effort="high",
    )
    db.commit()
    return refs


def _evidence(db, org_id: str, workspace_id: str, *, evidence_id: str):
    row = EvidenceRecord(
        id=evidence_id,
        tenant_id=org_id,
        workspace_id=workspace_id,
        evidence_type="operator_verification",
        field_id="field-1",
        block_id="block-a",
        title="Verified field record",
        summary="Operator recorded the observed state after the operation.",
        value_json={"verified": True},
        confidence=0.95,
        quality_status="verified",
        citation_label="Verified field record",
        metadata_json={},
    )
    db.add(row)
    db.commit()
    return row


def test_memory_api_requires_idempotency_key_for_mutations():
    with pytest.raises(HTTPException) as exc:
        api._idempotency_key(None)
    assert exc.value.status_code == 428


def test_viewer_is_read_only(monkeypatch):
    db = _db()
    try:
        owner, viewer, org, workspace = _seed_org(db)
        refs = _life(db, owner, org, workspace)
        monkeypatch.setattr(api, "require_feature", lambda *_args, **_kwargs: None)
        with pytest.raises(HTTPException) as exc:
            api.approve_decision(refs.lifecycle_id, "viewer-approve", org.id, viewer, db)
        assert exc.value.status_code == 403
    finally:
        db.close()


def test_execution_evidence_cannot_cross_tenant(monkeypatch):
    db = _db()
    try:
        owner, _viewer, org, workspace = _seed_org(db)
        refs = _life(db, owner, org, workspace)
        monkeypatch.setattr(api, "require_feature", lambda *_args, **_kwargs: None)
        api.approve_decision(refs.lifecycle_id, "approve-1", org.id, owner, db)
        _evidence(db, "other-tenant", workspace.id, evidence_id="foreign-evidence")
        with pytest.raises(HTTPException) as exc:
            api.mark_executed(
                refs.lifecycle_id,
                api.ExecutionEvidencePayload(execution_evidence_ids=["foreign-evidence"]),
                "execution-foreign",
                org.id,
                owner,
                db,
            )
        assert exc.value.status_code == 422
        lifecycle = api.get_lifecycle(refs.lifecycle_id, org.id, owner, db)
        assert lifecycle["state"] == "approved"
    finally:
        db.close()


def test_full_authorized_api_lifecycle_uses_durable_evidence(monkeypatch):
    db = _db()
    try:
        owner, _viewer, org, workspace = _seed_org(db)
        refs = _life(db, owner, org, workspace)
        evidence = _evidence(db, org.id, workspace.id, evidence_id="proof-1")
        monkeypatch.setattr(api, "require_feature", lambda *_args, **_kwargs: None)

        approved = api.approve_decision(refs.lifecycle_id, "approve-2", org.id, owner, db)
        assert approved["state"] == "approved"
        executed = api.mark_executed(
            refs.lifecycle_id,
            api.ExecutionEvidencePayload(execution_evidence_ids=[evidence.id]),
            "executed-2",
            org.id,
            owner,
            db,
        )
        assert executed["state"] == "executed"
        verified = api.mark_verified(
            refs.lifecycle_id,
            api.VerificationPayload(
                verification_evidence_ids=[evidence.id],
                outcome="effective",
                verification_status="complete",
            ),
            "verified-2",
            org.id,
            owner,
            db,
        )
        assert verified["state"] == "verified"
        assert verified["outcome"] == "effective"
        assert [event["to_state"] for event in verified["events"]] == [
            "proposed", "awaiting_approval", "approved", "executed", "verified"
        ]
    finally:
        db.close()


def test_decision_read_does_not_expose_internal_model_identity(monkeypatch):
    db = _db()
    try:
        owner, _viewer, org, workspace = _seed_org(db)
        refs = _life(db, owner, org, workspace)
        monkeypatch.setattr(api, "require_feature", lambda *_args, **_kwargs: None)
        body = api.get_decision(refs.decision_snapshot_id, False, org.id, owner, db)
        assert "model_name" not in body
        assert "model_provider" not in body
        assert body["snapshot_hash"]
        assert body["lifecycle"]["state"] == "awaiting_approval"
    finally:
        db.close()

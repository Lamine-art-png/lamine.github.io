from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401 - register full metadata
from app.db.base import Base
from app.models.intelligence_memory import DecisionSnapshot, ImmutableIntelligenceMemoryError
from app.services.decision_memory import (
    DecisionMemoryConflict,
    DecisionMemoryScopeError,
    decision_requires_human_approval,
    infer_decision_domain,
    persist_decision_snapshot,
)
from app.services.field_state_memory import persist_field_state
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _packet(org="org-1"):
    return IntelligenceGroundingPacket(
        generated_at="2026-08-21T20:00:00Z",
        organization_id=org,
        workspace_id="ws-1",
        field_id="field-1",
        observed_facts=[
            EvidenceSignal(
                evidence_id="ev-1",
                source_type="meter_reading",
                classification="observed",
                information_class="OBSERVED",
                title="Flow meter",
                statement="Measured flow is 120 gpm.",
                organization_id=org,
                workspace_id="ws-1",
                field_id="field-1",
                block_id="block-a",
                confidence_score=0.9,
                provenance={"operational_eligible": True},
            )
        ],
        grounding_confidence=0.8,
    )


def _decision(minutes=None, approval=True):
    action = "Inspect valve 2" if minutes is None else f"Run irrigation for {minutes} minutes"
    return {
        "answer": "Review current field conditions.",
        "recommendations": [
            {
                "action": action,
                "requires_human_approval": approval,
                "evidence_ids": ["ev-1"],
                "verification": "Record the result.",
            }
        ],
    }


def test_snapshot_is_idempotent_for_identical_content():
    db = _db()
    try:
        snapshot1, created1 = persist_decision_snapshot(
            db,
            _packet(),
            _decision(),
            idempotency_key="decision-1",
            task="inspection",
            question="What should I inspect?",
        )
        db.commit()
        snapshot2, created2 = persist_decision_snapshot(
            db,
            _packet(),
            _decision(),
            idempotency_key="decision-1",
            task="inspection",
            question="What should I inspect?",
        )
        assert created1 is True
        assert created2 is False
        assert snapshot2.id == snapshot1.id
        assert db.query(DecisionSnapshot).count() == 1
    finally:
        db.close()


def test_reused_idempotency_key_with_changed_content_fails_closed():
    db = _db()
    try:
        persist_decision_snapshot(db, _packet(), _decision(), idempotency_key="decision-1", task="inspection")
        db.commit()
        try:
            persist_decision_snapshot(db, _packet(), _decision(minutes=20), idempotency_key="decision-1", task="inspection")
            assert False, "changed content must fail idempotency"
        except DecisionMemoryConflict:
            pass
    finally:
        db.close()


def test_snapshot_links_only_same_organization_field_state_revision():
    db = _db()
    try:
        _current, revision, _ = persist_field_state(db, _packet(org="org-1"))
        db.commit()
        try:
            persist_decision_snapshot(
                db,
                _packet(org="org-2"),
                _decision(),
                idempotency_key="decision-cross-org",
                task="inspection",
                field_state_revision_id=revision.id,
            )
            assert False, "cross-organization revision must be rejected"
        except DecisionMemoryScopeError:
            pass
    finally:
        db.close()


def test_snapshot_stores_exact_evidence_graph_and_internal_model_identity():
    db = _db()
    try:
        snapshot, _ = persist_decision_snapshot(
            db,
            _packet(),
            _decision(minutes=20),
            idempotency_key="decision-2",
            task="irrigation_decision",
            model_provider="openai",
            model_name="gpt-5.6-sol",
            reasoning_effort="high",
        )
        db.commit()
        assert snapshot.evidence_graph_json["observed_facts"][0]["evidence_id"] == "ev-1"
        assert snapshot.evidence_ids_json == ["ev-1"]
        assert snapshot.model_name == "gpt-5.6-sol"
        assert snapshot.domain == "water"
        assert len(snapshot.snapshot_hash) == 64
    finally:
        db.close()


def test_snapshot_is_immutable_through_orm():
    db = _db()
    try:
        snapshot, _ = persist_decision_snapshot(db, _packet(), _decision(), idempotency_key="decision-3", task="inspection")
        db.commit()
        snapshot.task = "changed"
        try:
            db.commit()
            assert False, "immutable decision snapshot update should fail"
        except ImmutableIntelligenceMemoryError:
            db.rollback()
    finally:
        db.close()


def test_domain_and_approval_helpers_are_deterministic():
    assert infer_decision_domain(task="analyze", question="Check irrigation flow") == "water"
    assert infer_decision_domain(task="analyze", question="Review pest and leaf stress") == "crop_health"
    assert decision_requires_human_approval(_decision(minutes=20, approval=True)) is True
    assert decision_requires_human_approval(_decision(approval=False)) is False

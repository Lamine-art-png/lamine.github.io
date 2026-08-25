from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401
from app.db.base import Base
from app.models.intelligence_memory import DecisionLifecycle, DecisionSnapshot, FieldStateRevision
from app.services.decision_memory import DecisionMemoryConflict
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket
from app.services.intelligence_memory_service import persist_grounded_decision_memory


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _packet():
    return IntelligenceGroundingPacket(
        generated_at="2026-08-22T20:00:00Z",
        organization_id="org-1",
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
                organization_id="org-1",
                workspace_id="ws-1",
                field_id="field-1",
                block_id="block-a",
                confidence_score=0.9,
                provenance={"operational_eligible": True},
            )
        ],
        grounding_confidence=0.8,
    )


def _decision(action="Run irrigation", approval=True):
    return {
        "answer": "Decision ready.",
        "recommendations": [
            {
                "action": action,
                "requires_human_approval": approval,
                "evidence_ids": ["ev-1"],
                "verification": "Verify the observed result.",
            }
        ],
    }


def test_memory_service_persists_one_connected_decision_chain():
    db = _db()
    try:
        refs = persist_grounded_decision_memory(
            db,
            _packet(),
            _decision(),
            request_id="request-1",
            task="irrigation_decision",
            question="What should I do?",
            user_id="user-1",
            model_provider="openai",
            model_name="gpt-5.6-sol",
            reasoning_effort="high",
        )
        db.commit()
        assert refs.requires_human_approval is True
        assert refs.lifecycle_state == "awaiting_approval"
        snapshot = db.query(DecisionSnapshot).one()
        lifecycle = db.query(DecisionLifecycle).one()
        revision = db.query(FieldStateRevision).one()
        assert snapshot.field_state_revision_id == revision.id == refs.field_state_revision_id
        assert lifecycle.decision_snapshot_id == snapshot.id == refs.decision_snapshot_id
        assert lifecycle.id == refs.lifecycle_id
        assert snapshot.model_name == "gpt-5.6-sol"
    finally:
        db.close()


def test_memory_service_is_idempotent_for_same_request_and_content():
    db = _db()
    try:
        args = dict(
            request_id="request-idempotent",
            task="inspection",
            question="What should I inspect?",
            user_id="user-1",
            model_provider="openai",
            model_name="gpt-5.6-terra",
            reasoning_effort="medium",
        )
        first = persist_grounded_decision_memory(db, _packet(), _decision("Inspect valve 2", False), **args)
        db.commit()
        second = persist_grounded_decision_memory(db, _packet(), _decision("Inspect valve 2", False), **args)
        db.commit()
        assert first.decision_snapshot_id == second.decision_snapshot_id
        assert first.lifecycle_id == second.lifecycle_id
        assert second.new_decision_snapshot is False
        assert second.new_lifecycle is False
        assert db.query(DecisionSnapshot).count() == 1
        assert db.query(FieldStateRevision).count() == 1
    finally:
        db.close()


def test_memory_service_rejects_same_request_identity_for_changed_decision():
    db = _db()
    try:
        common = dict(
            request_id="request-conflict",
            task="decision",
            question="What should I do?",
            user_id="user-1",
            model_provider="openai",
            model_name="gpt-5.6-sol",
            reasoning_effort="high",
        )
        persist_grounded_decision_memory(db, _packet(), _decision("Inspect valve 2", False), **common)
        db.commit()
        try:
            persist_grounded_decision_memory(db, _packet(), _decision("Inspect pump 3", False), **common)
            assert False, "changed decision under one request ID must fail"
        except DecisionMemoryConflict:
            db.rollback()
    finally:
        db.close()

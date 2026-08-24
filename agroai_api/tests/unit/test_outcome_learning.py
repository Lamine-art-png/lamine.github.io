from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401
from app.db.base import Base
from app.models.intelligence_memory import DecisionLifecycle, DecisionLifecycleEvent, DecisionSnapshot
from app.models.operational_records import EvidenceRecord
from app.services.outcome_learning import (
    VERIFIED_OUTCOME_EVIDENCE_TYPE,
    OutcomeLearningError,
    build_outcome_learning_summary,
    materialize_verified_outcome_evidence,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(db, *, snapshot_id="snap-1", field_id="field-1"):
    row = DecisionSnapshot(
        id=snapshot_id,
        organization_id="org-1",
        workspace_id=None,
        user_id=None,
        field_state_revision_id=None,
        intelligence_run_id=None,
        legacy_decision_run_id=None,
        field_id=field_id,
        block_id="block-a",
        domain="water",
        task="decision",
        question="Review irrigation",
        decision_schema_version="test",
        grounding_schema_version="test",
        science_ruleset_version="test",
        evidence_graph_json={},
        evidence_ids_json=["ev-1"],
        science_trace_json=[
            {
                "rule_id": "irrigation.measured_volume.v1",
                "status": "computed",
                "value": 6.0,
                "evidence_ids": ["ev-1"],
            }
        ],
        decision_json={"recommendations": [{"action": "Review measured irrigation volume"}]},
        grounding_confidence=0.84,
        model_provider="internal",
        model_name="internal",
        reasoning_effort="medium",
        policy_version="test",
        action_policy_version="test",
        snapshot_hash=f"hash-{snapshot_id}",
        idempotency_key=f"key-{snapshot_id}",
    )
    db.add(row)
    db.flush()
    return row


def _verified_lifecycle(db, snapshot, *, lifecycle_id="life-1", outcome="effective"):
    now = datetime.utcnow()
    lifecycle = DecisionLifecycle(
        id=lifecycle_id,
        decision_snapshot_id=snapshot.id,
        organization_id="org-1",
        workspace_id=None,
        state="verified",
        version=4,
        requires_human_approval=True,
        approved_at=now,
        executed_at=now,
        verified_at=now,
        verification_status="complete",
        outcome=outcome,
    )
    db.add(lifecycle)
    db.flush()
    db.add(
        DecisionLifecycleEvent(
            lifecycle_id=lifecycle.id,
            organization_id="org-1",
            workspace_id=None,
            sequence=4,
            from_state="verification_pending",
            to_state="verified",
            event_type="verification_completed",
            actor_type="user",
            actor_user_id=None,
            payload_json={
                "lifecycle_policy_version": "test",
                "outcome": outcome,
                "verification_evidence_ids": ["verify-1"],
            },
            idempotency_key=f"verified-{lifecycle.id}",
        )
    )
    db.flush()
    return lifecycle


def test_verified_lifecycle_materializes_reusable_learning_evidence_idempotently():
    db = _db()
    try:
        lifecycle = _verified_lifecycle(db, _snapshot(db))
        first = materialize_verified_outcome_evidence(db, organization_id="org-1", lifecycle_id=lifecycle.id)
        second = materialize_verified_outcome_evidence(db, organization_id="org-1", lifecycle_id=lifecycle.id)
        db.commit()
        assert first.created is True
        assert second.created is False
        assert first.evidence_id == second.evidence_id
        row = db.query(EvidenceRecord).filter(EvidenceRecord.id == first.evidence_id).one()
        assert row.evidence_type == VERIFIED_OUTCOME_EVIDENCE_TYPE
        assert row.quality_status == "verified"
        assert row.metadata_json["operational_eligible"] is False
        assert row.value_json["outcome"] == "effective"
        assert row.value_json["science_rule_ids"] == ["irrigation.measured_volume.v1"]
    finally:
        db.close()


def test_non_verified_decision_cannot_be_promoted_to_learning_evidence():
    db = _db()
    try:
        snapshot = _snapshot(db)
        lifecycle = DecisionLifecycle(
            id="life-pending",
            decision_snapshot_id=snapshot.id,
            organization_id="org-1",
            state="awaiting_approval",
            version=2,
            requires_human_approval=True,
        )
        db.add(lifecycle)
        db.flush()
        try:
            materialize_verified_outcome_evidence(db, organization_id="org-1", lifecycle_id=lifecycle.id)
            assert False, "unverified decision must not become outcome evidence"
        except OutcomeLearningError:
            pass
    finally:
        db.close()


def test_cross_organization_lifecycle_cannot_be_materialized():
    db = _db()
    try:
        lifecycle = _verified_lifecycle(db, _snapshot(db))
        try:
            materialize_verified_outcome_evidence(db, organization_id="org-2", lifecycle_id=lifecycle.id)
            assert False, "cross-organization learning must fail"
        except OutcomeLearningError:
            pass
    finally:
        db.close()


def test_learning_summary_is_tenant_scoped_and_never_auto_tunes_science():
    db = _db()
    try:
        _verified_lifecycle(db, _snapshot(db, snapshot_id="snap-a"), lifecycle_id="life-a", outcome="effective")
        _verified_lifecycle(db, _snapshot(db, snapshot_id="snap-b"), lifecycle_id="life-b", outcome="deviated")
        rejected_snapshot = _snapshot(db, snapshot_id="snap-c")
        db.add(
            DecisionLifecycle(
                id="life-c",
                decision_snapshot_id=rejected_snapshot.id,
                organization_id="org-1",
                state="rejected",
                version=3,
                requires_human_approval=True,
                rejected_at=datetime.utcnow(),
                rejection_reason="Operator rejected it.",
            )
        )
        db.flush()
        summary = build_outcome_learning_summary(db, organization_id="org-1", field_id="field-1")
        assert summary["decision_count"] == 3
        assert summary["verified_count"] == 2
        assert summary["human_rejection_count"] == 1
        assert summary["verified_outcome_distribution"] == {"deviated": 1, "effective": 1}
        assert summary["automatic_parameter_updates"] is False
        assert summary["automatic_policy_updates"] is False
        review = summary["calibration_review"][0]
        assert review["rule_id"] == "irrigation.measured_volume.v1"
        assert review["proposed_parameter_change"] is None
        assert review["status"] == "human_review_required"
    finally:
        db.close()

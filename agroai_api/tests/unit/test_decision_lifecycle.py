from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401 - register full metadata
from app.db.base import Base
from app.models.intelligence_memory import DecisionLifecycleEvent, ImmutableIntelligenceMemoryError
from app.services.decision_lifecycle import (
    LifecycleIdempotencyConflict,
    LifecycleTransitionError,
    create_decision_lifecycle,
    transition_decision_lifecycle,
)
from app.services.decision_memory import persist_decision_snapshot
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(db, *, key="snapshot-1", approval=True):
    packet = IntelligenceGroundingPacket(
        generated_at="2026-08-21T20:00:00Z",
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
    decision = {
        "answer": "Decision ready for policy review.",
        "recommendations": [
            {
                "action": "Run irrigation" if approval else "Inspect valve 2",
                "requires_human_approval": approval,
                "evidence_ids": ["ev-1"],
                "verification": "Record the observed result.",
            }
        ],
    }
    snapshot, _ = persist_decision_snapshot(db, packet, decision, idempotency_key=key, task="decision")
    db.flush()
    return snapshot


def test_human_approval_decision_starts_awaiting_approval_with_append_only_events():
    db = _db()
    try:
        lifecycle, created = create_decision_lifecycle(db, _snapshot(db), requires_human_approval=True, idempotency_key="life-1")
        db.commit()
        events = db.query(DecisionLifecycleEvent).filter(DecisionLifecycleEvent.lifecycle_id == lifecycle.id).order_by(DecisionLifecycleEvent.sequence).all()
        assert created is True
        assert lifecycle.state == "awaiting_approval"
        assert lifecycle.version == 2
        assert [(row.from_state, row.to_state) for row in events] == [(None, "proposed"), ("proposed", "awaiting_approval")]
    finally:
        db.close()


def test_system_cannot_approve_decision_that_requires_human():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(db, _snapshot(db), requires_human_approval=True, idempotency_key="life-2")
        try:
            transition_decision_lifecycle(db, lifecycle.id, to_state="approved", event_type="approved", actor_type="system", idempotency_key="life-2:approve")
            assert False, "system approval must be rejected"
        except LifecycleTransitionError:
            pass
    finally:
        db.close()


def test_full_approved_execution_verification_path_requires_proof():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(db, _snapshot(db), requires_human_approval=True, idempotency_key="life-3")
        transition_decision_lifecycle(
            db, lifecycle.id, to_state="approved", event_type="human_approved", actor_type="user",
            actor_user_id="user-1", idempotency_key="life-3:approved",
        )
        assert lifecycle.state == "approved"
        assert lifecycle.approved_by_user_id == "user-1"

        try:
            transition_decision_lifecycle(
                db, lifecycle.id, to_state="executed", event_type="execution_recorded",
                actor_type="provider", idempotency_key="life-3:executed-empty",
            )
            assert False, "execution without proof must fail"
        except LifecycleTransitionError:
            pass

        transition_decision_lifecycle(
            db, lifecycle.id, to_state="executed", event_type="execution_recorded", actor_type="provider",
            idempotency_key="life-3:executed",
            payload={"provider_event_id": "provider-event-9", "execution_evidence_ids": ["execution-1"]},
        )
        transition_decision_lifecycle(
            db, lifecycle.id, to_state="verification_pending", event_type="verification_started", actor_type="system",
            idempotency_key="life-3:verification-pending", payload={"verification_status": "pending_24h"},
        )
        try:
            transition_decision_lifecycle(
                db, lifecycle.id, to_state="verified", event_type="verification_complete", actor_type="system",
                idempotency_key="life-3:verified-empty", payload={"outcome": "effective"},
            )
            assert False, "verification without evidence must fail"
        except LifecycleTransitionError:
            pass

        transition_decision_lifecycle(
            db, lifecycle.id, to_state="verified", event_type="verification_complete", actor_type="system",
            idempotency_key="life-3:verified",
            payload={
                "outcome": "effective", "verification_status": "complete",
                "verification_evidence_ids": ["verification-1", "verification-2"],
            },
        )
        db.commit()
        assert lifecycle.state == "verified"
        assert lifecycle.outcome == "effective"
        assert lifecycle.verification_status == "complete"
        assert lifecycle.version == 6
        assert db.query(DecisionLifecycleEvent).filter(DecisionLifecycleEvent.lifecycle_id == lifecycle.id).count() == 6
    finally:
        db.close()


def test_side_effect_free_decision_auto_approves_without_fake_human_actor():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(
            db, _snapshot(db, key="snapshot-safe", approval=False),
            requires_human_approval=False, idempotency_key="life-safe",
        )
        db.commit()
        assert lifecycle.state == "approved"
        assert lifecycle.approved_at is not None
        assert lifecycle.approved_by_user_id is None
    finally:
        db.close()


def test_rejection_requires_authenticated_user_and_reason():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(db, _snapshot(db), requires_human_approval=True, idempotency_key="life-reject")
        for kwargs in (
            {"actor_type": "system", "actor_user_id": None, "payload": {"reason": "No"}},
            {"actor_type": "user", "actor_user_id": "user-1", "payload": {}},
        ):
            try:
                transition_decision_lifecycle(
                    db, lifecycle.id, to_state="rejected", event_type="human_rejected",
                    idempotency_key=f"life-reject:{kwargs['actor_type']}:{bool(kwargs['payload'])}", **kwargs,
                )
                assert False, "invalid rejection must fail"
            except LifecycleTransitionError:
                pass
        transition_decision_lifecycle(
            db, lifecycle.id, to_state="rejected", event_type="human_rejected", actor_type="user",
            actor_user_id="user-1", idempotency_key="life-reject:valid",
            payload={"reason": "Field operator rejected the recommendation."},
        )
        assert lifecycle.state == "rejected"
    finally:
        db.close()


def test_expired_decision_cannot_be_approved():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(
            db, _snapshot(db, key="snapshot-expired"), requires_human_approval=True,
            idempotency_key="life-expired", expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        try:
            transition_decision_lifecycle(
                db, lifecycle.id, to_state="approved", event_type="human_approved", actor_type="user",
                actor_user_id="user-1", idempotency_key="life-expired:approve",
            )
            assert False, "expired decision must not be approved"
        except LifecycleTransitionError:
            pass
    finally:
        db.close()


def test_transition_idempotency_requires_exact_actor_and_payload_match():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(db, _snapshot(db, key="snapshot-idem"), requires_human_approval=True, idempotency_key="life-idem")
        kwargs = dict(
            to_state="approved", event_type="human_approved", actor_type="user",
            actor_user_id="user-1", idempotency_key="life-idem:transition", payload={"note": "approved in portal"},
        )
        _life, event1, created1 = transition_decision_lifecycle(db, lifecycle.id, **kwargs)
        _life, event2, created2 = transition_decision_lifecycle(db, lifecycle.id, **kwargs)
        assert created1 is True
        assert created2 is False
        assert event2.id == event1.id

        for changed in (
            {**kwargs, "actor_user_id": "user-2"},
            {**kwargs, "payload": {"note": "different"}},
            {**kwargs, "event_type": "different_event"},
        ):
            try:
                transition_decision_lifecycle(db, lifecycle.id, **changed)
                assert False, "same idempotency key for changed transition must fail"
            except LifecycleIdempotencyConflict:
                pass
    finally:
        db.close()


def test_lifecycle_creation_rejects_changed_approval_policy():
    db = _db()
    try:
        snapshot = _snapshot(db, key="snapshot-policy")
        create_decision_lifecycle(db, snapshot, requires_human_approval=True, idempotency_key="life-policy")
        try:
            create_decision_lifecycle(db, snapshot, requires_human_approval=False, idempotency_key="life-policy")
            assert False, "same snapshot cannot change approval policy"
        except LifecycleIdempotencyConflict:
            pass
    finally:
        db.close()


def test_lifecycle_event_is_immutable_through_orm():
    db = _db()
    try:
        lifecycle, _ = create_decision_lifecycle(db, _snapshot(db, key="snapshot-immutable"), requires_human_approval=True, idempotency_key="life-immutable")
        db.commit()
        event = db.query(DecisionLifecycleEvent).filter(DecisionLifecycleEvent.lifecycle_id == lifecycle.id).first()
        event.event_type = "tampered"
        try:
            db.commit()
            assert False, "append-only event update should fail"
        except ImmutableIntelligenceMemoryError:
            db.rollback()
    finally:
        db.close()

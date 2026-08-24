from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.models.intelligence_memory import (
    DecisionLifecycle,
    DecisionLifecycleEvent,
    DecisionSnapshot,
    FieldState,
    FieldStateRevision,
)
from app.models.saas import Organization, User, Workspace
from app.services.decision_lifecycle import create_decision_lifecycle, transition_decision_lifecycle
from app.services.decision_memory import persist_decision_snapshot
from app.services.field_state_memory import persist_field_state
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket


POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is not configured")


def _seed(Session):
    db = Session()
    suffix = uuid.uuid4().hex
    user = User(
        email=f"intelligence-memory-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Intelligence memory concurrency",
        slug=f"intelligence-memory-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    db.add(org)
    db.flush()
    workspace = Workspace(organization_id=org.id, name="Memory", mode="evaluation")
    db.add(workspace)
    db.commit()
    db.close()
    return user.id, org.id, workspace.id


def _packet(org_id: str, workspace_id: str) -> IntelligenceGroundingPacket:
    return IntelligenceGroundingPacket(
        generated_at="2026-08-22T12:00:00Z",
        organization_id=org_id,
        workspace_id=workspace_id,
        field_id="field-concurrent",
        observed_facts=[
            EvidenceSignal(
                evidence_id="meter-concurrent",
                source_type="meter_reading",
                classification="observed",
                information_class="OBSERVED",
                title="Flow meter",
                statement="Measured flow is 120 gpm.",
                organization_id=org_id,
                workspace_id=workspace_id,
                field_id="field-concurrent",
                block_id="block-a",
                observed_at="2026-08-22T11:55:00Z",
                freshness_score=0.98,
                quality_score=0.95,
                confidence_score=0.92,
                provenance={"operational_eligible": True},
            )
        ],
        grounding_confidence=0.82,
    )


def _decision() -> dict:
    return {
        "answer": "Review the current irrigation decision.",
        "recommendations": [
            {
                "action": "Run irrigation",
                "requires_human_approval": True,
                "evidence_ids": ["meter-concurrent"],
                "verification": "Verify execution and field response.",
            }
        ],
    }


def test_postgres_first_write_field_state_and_snapshot_are_concurrency_safe():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    _user_id, org_id, workspace_id = _seed(Session)
    packet = _packet(org_id, workspace_id)
    barrier = threading.Barrier(2)

    def write_state():
        db = Session()
        try:
            barrier.wait()
            current, revision, created = persist_field_state(db, packet)
            db.commit()
            return current.id, revision.id, created
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        state_results = list(pool.map(lambda _n: write_state(), range(2)))
    assert len({row[0] for row in state_results}) == 1
    assert len({row[1] for row in state_results}) == 1
    assert sorted(row[2] for row in state_results) == [False, True]

    verify = Session()
    revision = verify.query(FieldStateRevision).filter(FieldStateRevision.organization_id == org_id).one()
    assert verify.query(FieldState).filter(FieldState.organization_id == org_id).count() == 1
    revision_id = revision.id
    verify.close()

    snapshot_barrier = threading.Barrier(2)

    def write_snapshot():
        db = Session()
        try:
            snapshot_barrier.wait()
            snapshot, created = persist_decision_snapshot(
                db,
                packet,
                _decision(),
                idempotency_key="concurrent-decision",
                task="irrigation_decision",
                field_state_revision_id=revision_id,
            )
            db.commit()
            return snapshot.id, created
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot_results = list(pool.map(lambda _n: write_snapshot(), range(2)))
    assert len({row[0] for row in snapshot_results}) == 1
    assert sorted(row[1] for row in snapshot_results) == [False, True]
    verify = Session()
    assert verify.query(DecisionSnapshot).filter(DecisionSnapshot.organization_id == org_id).count() == 1
    verify.close()
    engine.dispose()


def test_postgres_lifecycle_creation_and_transition_are_exactly_once_under_concurrency():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, org_id, workspace_id = _seed(Session)
    packet = _packet(org_id, workspace_id)
    seed = Session()
    _state, revision, _ = persist_field_state(seed, packet)
    snapshot, _ = persist_decision_snapshot(
        seed,
        packet,
        _decision(),
        idempotency_key="lifecycle-snapshot",
        task="irrigation_decision",
        field_state_revision_id=revision.id,
    )
    seed.commit()
    snapshot_id = snapshot.id
    seed.close()
    barrier = threading.Barrier(2)

    def create_life():
        db = Session()
        try:
            local_snapshot = db.query(DecisionSnapshot).filter(DecisionSnapshot.id == snapshot_id).one()
            barrier.wait()
            lifecycle, created = create_decision_lifecycle(
                db,
                local_snapshot,
                requires_human_approval=True,
                idempotency_key="concurrent-life",
            )
            db.commit()
            return lifecycle.id, created
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        life_results = list(pool.map(lambda _n: create_life(), range(2)))
    lifecycle_id = life_results[0][0]
    assert len({row[0] for row in life_results}) == 1
    assert sorted(row[1] for row in life_results) == [False, True]

    approval_barrier = threading.Barrier(2)

    def approve():
        db = Session()
        try:
            approval_barrier.wait()
            lifecycle, event, created = transition_decision_lifecycle(
                db,
                lifecycle_id,
                to_state="approved",
                event_type="human_approved",
                actor_type="user",
                actor_user_id=user_id,
                idempotency_key="concurrent-life:approved",
                payload={"source": "portal"},
            )
            db.commit()
            return lifecycle.version, event.id, created
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        approval_results = list(pool.map(lambda _n: approve(), range(2)))
    assert len({row[1] for row in approval_results}) == 1
    assert sorted(row[2] for row in approval_results) == [False, True]
    verify = Session()
    lifecycle = verify.query(DecisionLifecycle).filter(DecisionLifecycle.id == lifecycle_id).one()
    events = verify.query(DecisionLifecycleEvent).filter(DecisionLifecycleEvent.lifecycle_id == lifecycle_id).all()
    assert lifecycle.state == "approved"
    assert lifecycle.version == 3
    assert len(events) == 3
    verify.close()
    engine.dispose()


def test_postgres_database_triggers_enforce_append_only_memory():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, org_id, workspace_id = _seed(Session)
    packet = _packet(org_id, workspace_id)
    seed = Session()
    state, revision, _ = persist_field_state(seed, packet)
    snapshot, _ = persist_decision_snapshot(
        seed,
        packet,
        _decision(),
        idempotency_key="immutable-snapshot",
        task="irrigation_decision",
        field_state_revision_id=revision.id,
    )
    lifecycle, _ = create_decision_lifecycle(seed, snapshot, requires_human_approval=True, idempotency_key="immutable-life")
    transition_decision_lifecycle(
        seed,
        lifecycle.id,
        to_state="approved",
        event_type="human_approved",
        actor_type="user",
        actor_user_id=user_id,
        idempotency_key="immutable-life:approved",
    )
    seed.commit()
    event_id = seed.query(DecisionLifecycleEvent).filter(DecisionLifecycleEvent.lifecycle_id == lifecycle.id).first().id
    state_id, revision_id, snapshot_id, lifecycle_id = state.id, revision.id, snapshot.id, lifecycle.id
    seed.close()

    mutations = (
        ("UPDATE field_state_revisions SET state_hash = :value WHERE id = :id", revision_id, "0" * 64),
        ("UPDATE decision_snapshots SET task = :value WHERE id = :id", snapshot_id, "tampered"),
        ("UPDATE decision_lifecycle_events SET event_type = :value WHERE id = :id", event_id, "tampered"),
    )
    for statement, row_id, value in mutations:
        db = Session()
        try:
            with pytest.raises(DBAPIError):
                db.execute(sa.text(statement), {"id": row_id, "value": value})
                db.commit()
            db.rollback()
        finally:
            db.close()

    for table, row_id in (("field_states", state_id), ("decision_lifecycles", lifecycle_id)):
        db = Session()
        try:
            with pytest.raises(DBAPIError):
                db.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
                db.commit()
            db.rollback()
        finally:
            db.close()
    engine.dispose()

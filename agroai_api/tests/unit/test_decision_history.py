from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401
from app.db.base import Base
from app.models.intelligence_memory import DecisionSnapshot
from app.services.decision_history import compare_decision_snapshots, previous_decision_snapshot


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(snapshot_id: str, created_at: datetime, *, evidence, science_value, recommendation, confidence, revision):
    return DecisionSnapshot(
        id=snapshot_id,
        organization_id="org-1",
        workspace_id=None,
        field_id="field-1",
        block_id="block-a",
        domain="water",
        task="decision",
        question="What changed?",
        decision_schema_version="test",
        grounding_schema_version="test",
        science_ruleset_version="test",
        evidence_graph_json={"conflicts": [], "unknowns": []},
        evidence_ids_json=evidence,
        science_trace_json=[{
            "rule_id": "irrigation.measured_volume.v1",
            "status": "computed",
            "value": science_value,
            "unit": "m3",
            "evidence_ids": evidence,
        }],
        decision_json={"recommendations": [{"action": recommendation}]},
        grounding_confidence=confidence,
        policy_version="test",
        action_policy_version="test",
        snapshot_hash=f"hash-{snapshot_id}",
        idempotency_key=f"key-{snapshot_id}",
        field_state_revision_id=revision,
        created_at=created_at,
    )


def test_change_explanation_is_derived_only_from_persisted_snapshot_differences():
    now = datetime.utcnow()
    before = _snapshot("before", now - timedelta(minutes=10), evidence=["ev-1"], science_value=6.0, recommendation="Inspect flow", confidence=0.7, revision="state-1")
    after = _snapshot("after", now, evidence=["ev-1", "ev-2"], science_value=8.0, recommendation="Review measured volume", confidence=0.82, revision="state-2")
    diff = compare_decision_snapshots(after, before)
    assert diff["changed"] is True
    assert diff["evidence"] == {"added": ["ev-2"], "removed": []}
    assert diff["science"]["changed"][0]["rule_id"] == "irrigation.measured_volume.v1"
    assert diff["recommendations"]["changed"] is True
    assert diff["confidence"]["delta"] == 0.12
    assert diff["field_state_revision"]["changed"] is True
    assert "evidence_changed" in diff["change_driver_codes"]
    assert "science_changed" in diff["change_driver_codes"]
    assert "confidence_changed" in diff["change_driver_codes"]
    assert "field_state_changed" in diff["change_driver_codes"]
    assert "recommendation_changed" in diff["change_driver_codes"]
    assert "The evidence set changed." in diff["change_drivers"]
    assert "One or more deterministic science results changed." in diff["change_drivers"]


def test_first_decision_does_not_invent_a_prior_cause():
    current = _snapshot("only", datetime.utcnow(), evidence=["ev-1"], science_value=6.0, recommendation="Inspect", confidence=0.7, revision="state-1")
    diff = compare_decision_snapshots(current, None)
    assert diff["first_decision_in_scope"] is True
    assert diff["changed"] is False
    assert diff["previous_decision_id"] is None
    assert diff["change_driver_codes"] == ["first_decision"]
    assert diff["change_drivers"] == ["No earlier immutable decision exists in the same field/domain scope."]


def test_previous_snapshot_is_tenant_field_domain_scoped():
    db = _db()
    try:
        now = datetime.utcnow()
        previous = _snapshot("previous", now - timedelta(minutes=5), evidence=["ev-1"], science_value=6.0, recommendation="Inspect", confidence=0.7, revision="state-1")
        current = _snapshot("current", now, evidence=["ev-2"], science_value=7.0, recommendation="Review", confidence=0.75, revision="state-2")
        other_field = _snapshot("other-field", now - timedelta(minutes=1), evidence=["ev-x"], science_value=9.0, recommendation="Ignore", confidence=0.9, revision="state-x")
        other_field.field_id = "field-2"
        db.add_all([previous, current, other_field])
        db.commit()
        found = previous_decision_snapshot(db, current)
        assert found is not None
        assert found.id == "previous"
    finally:
        db.close()
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401 - register full metadata
from app.db.base import Base
from app.models.intelligence_memory import FieldStateRevision, ImmutableIntelligenceMemoryError
from app.services.field_state_memory import build_field_state_projection, persist_field_state
from app.services.intelligence_grounding import EvidenceConflict, EvidenceSignal, IntelligenceGroundingPacket, ScienceResult


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _packet(*, statement="Measured soil moisture is 31%.", generated="2026-08-21T20:00:00Z"):
    signal = EvidenceSignal(
        evidence_id="sensor-1",
        source_type="sensor",
        classification="observed",
        information_class="OBSERVED",
        title="Root-zone sensor",
        statement=statement,
        organization_id="org-1",
        workspace_id="ws-1",
        field_id="field-1",
        block_id="block-a",
        observed_at="2026-08-21T19:55:00Z",
        freshness_score=0.98,
        quality_score=0.95,
        confidence_score=0.93,
        units="%",
        provenance={"operational_eligible": True, "source": "sensor"},
    )
    science = ScienceResult(
        rule_id="fao56.etc.single_kc.v1",
        name="FAO-56 crop evapotranspiration",
        status="computed",
        value=4.0,
        unit="mm",
        inputs={"eto_mm": 5.0, "kc": 0.8},
        evidence_ids=["weather-1", "kc-1"],
        formula="ETc = Kc × ETo",
        confidence_score=0.9,
    )
    return IntelligenceGroundingPacket(
        generated_at=generated,
        organization_id="org-1",
        workspace_id="ws-1",
        field_id="field-1",
        crop_type="wine grapes",
        observed_facts=[signal],
        unknowns=["Validated irrigation efficiency is unavailable."],
        conflicts=[
            EvidenceConflict(
                metric="flow_rate_gpm",
                evidence_ids=["flow-1", "flow-2"],
                values=[100.0, 140.0],
                severity="high",
                reason="Conflicting flow readings.",
            )
        ],
        science_checks=[science],
        source_health={"operational_eligible_count": 1},
        grounding_confidence=0.72,
        decision_constraints=["Human approval required for physical execution."],
    )


def test_projection_keeps_unknown_and_conflict_state_explicit():
    projection = build_field_state_projection(_packet())
    assert projection["identity"]["field_id"] == "field-1"
    assert projection["identity"]["block_id"] == "block-a"
    assert projection["observed"]["water"][0]["status"] == "observed"
    assert projection["conflict_metrics"] == ["flow_rate_gpm"]
    assert projection["science"][0]["value"] == 4.0


def test_identical_semantic_state_does_not_create_revision_noise():
    db = _db()
    try:
        current1, revision1, created1 = persist_field_state(db, _packet())
        db.commit()
        current2, revision2, created2 = persist_field_state(db, _packet(generated="2026-08-21T20:10:00Z"))
        db.commit()
        assert created1 is True
        assert created2 is False
        assert current2.id == current1.id
        assert revision2.id == revision1.id
        assert current2.revision == 1
        assert db.query(FieldStateRevision).count() == 1
    finally:
        db.close()


def test_changed_semantic_state_creates_hash_chained_revision():
    db = _db()
    try:
        current1, revision1, _ = persist_field_state(db, _packet())
        db.commit()
        old_hash = revision1.state_hash
        current2, revision2, created = persist_field_state(
            db,
            _packet(statement="Measured soil moisture is 28%."),
        )
        db.commit()
        assert created is True
        assert current2.id == current1.id
        assert current2.revision == 2
        assert revision2.revision == 2
        assert revision2.previous_revision_hash == old_hash
        assert revision2.state_hash != old_hash
        assert db.query(FieldStateRevision).count() == 2
    finally:
        db.close()


def test_field_state_revision_is_immutable_through_orm():
    db = _db()
    try:
        _current, revision, _ = persist_field_state(db, _packet())
        db.commit()
        revision.state_hash = "0" * 64
        try:
            db.commit()
            assert False, "immutable revision update should fail"
        except ImmutableIntelligenceMemoryError:
            db.rollback()
    finally:
        db.close()

from app.services.intelligence_grounding import (
    EvidenceConflict,
    EvidenceSignal,
    IntelligenceGroundingPacket,
    ScienceResult,
)
from app.services.intelligence_specialists import analyze_specialist, run_specialists


def _packet() -> IntelligenceGroundingPacket:
    return IntelligenceGroundingPacket(
        generated_at="2026-08-23T18:00:00Z",
        organization_id="org-1",
        workspace_id="ws-1",
        field_id="field-1",
        observed_facts=[
            EvidenceSignal(
                evidence_id="water-1",
                source_type="meter_reading",
                classification="observed",
                information_class="OBSERVED",
                title="Irrigation flow meter",
                statement="Measured irrigation flow is available.",
                organization_id="org-1",
                workspace_id="ws-1",
                field_id="field-1",
                confidence_score=0.92,
                provenance={"operational_eligible": True},
            ),
            EvidenceSignal(
                evidence_id="crop-1",
                source_type="field_observation",
                classification="observed",
                information_class="OBSERVED",
                title="Leaf observation",
                statement="Operator recorded a leaf symptom in the west row.",
                organization_id="org-1",
                workspace_id="ws-1",
                field_id="field-1",
                confidence_score=0.78,
                provenance={"operational_eligible": False},
            ),
        ],
        unknowns=["validated irrigation efficiency", "crop health follow-up image"],
        conflicts=[
            EvidenceConflict(
                metric="flow_rate_gpm",
                evidence_ids=["water-1", "water-2"],
                values=[120.0, 160.0],
                severity="high",
                reason="Two current field-scoped meters disagree.",
            )
        ],
        science_checks=[
            ScienceResult(
                rule_id="irrigation.measured_volume.v1",
                name="Measured irrigation volume",
                status="computed",
                value=6.0,
                unit="m3",
                inputs={"flow_m3h": 12.0, "runtime_minutes": 30.0},
                evidence_ids=["water-1"],
                formula="Volume = flow × runtime",
                confidence_score=0.9,
            )
        ],
        grounding_confidence=0.86,
    )


def test_water_specialist_promotes_only_relevant_observed_and_registry_science():
    result = analyze_specialist("water", _packet())
    assert result.status == "conflict_review"
    assert [row["evidence_id"] for row in result.observed_evidence] == ["water-1"]
    assert [row["rule_id"] for row in result.deterministic_findings] == ["irrigation.measured_volume.v1"]
    assert result.confidence_cap <= 0.60
    assert result.side_effect_free is True
    assert {row.action_kind for row in result.next_evidence_actions} <= {"inspection", "data_collection"}


def test_crop_health_specialist_does_not_turn_observation_into_diagnosis_or_execution():
    result = analyze_specialist("crop_health", _packet())
    assert [row["evidence_id"] for row in result.observed_evidence] == ["crop-1"]
    assert result.deterministic_findings == []
    assert all(row.action_kind in {"inspection", "data_collection"} for row in result.next_evidence_actions)
    combined = " ".join(row.action for row in result.next_evidence_actions).casefold()
    assert "spray" not in combined
    assert "apply" not in combined
    assert "execute" not in combined


def test_reporting_specialist_can_summarize_cross_domain_evidence_without_side_effects():
    result = analyze_specialist("reporting", _packet())
    assert {row["evidence_id"] for row in result.observed_evidence} == {"water-1", "crop-1"}
    assert result.side_effect_free is True
    assert result.status == "conflict_review"


def test_empty_domain_requests_evidence_and_caps_confidence():
    packet = IntelligenceGroundingPacket(
        generated_at="2026-08-23T18:00:00Z",
        organization_id="org-1",
        grounding_confidence=0.95,
    )
    result = analyze_specialist("equipment", packet)
    assert result.status == "evidence_limited"
    assert result.confidence_cap <= 0.30
    assert result.next_evidence_actions[0].action_kind == "data_collection"


def test_all_specialists_are_explicitly_side_effect_free():
    results = run_specialists(_packet())
    assert [row.domain for row in results] == ["water", "crop_health", "equipment", "assurance", "reporting"]
    assert all(row.side_effect_free for row in results)
    assert all(
        action.action_kind in {"inspection", "data_collection"}
        for row in results
        for action in row.next_evidence_actions
    )

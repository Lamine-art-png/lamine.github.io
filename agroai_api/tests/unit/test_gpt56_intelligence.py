from __future__ import annotations

from app.services.gpt56_intelligence import (
    ConfidenceBlock,
    GPT56Decision,
    GroundedFact,
    Recommendation,
    select_model,
    validate_decision,
)
from app.services.intelligence_grounding import EvidenceSignal, IntelligenceGroundingPacket


def _packet():
    return IntelligenceGroundingPacket(
        generated_at="2026-08-21T20:00:00+00:00",
        organization_id="org-1",
        workspace_id="ws-1",
        field_id="field-1",
        observed_facts=[
            EvidenceSignal(
                evidence_id="ev-1",
                source_type="telemetry",
                classification="observed",
                title="Flow meter",
                statement="Measured flow was 120 gpm.",
                freshness_score=1.0,
                quality_score=0.95,
                confidence_score=0.92,
            )
        ],
        grounding_confidence=0.82,
        decision_constraints=[],
    )


def _decision(**overrides):
    base = dict(
        answer="The measured flow is 120 gpm.",
        facts=[GroundedFact(claim="Measured flow is 120 gpm.", evidence_ids=["ev-1"])],
        derived_findings=[],
        hypotheses=[],
        unknowns=[],
        conflicts=[],
        recommendations=[],
        risk_flags=[],
        confidence=ConfidenceBlock(level="high", score=0.95, drivers=["recent telemetry"]),
    )
    base.update(overrides)
    return GPT56Decision(**base)


def test_model_routing_uses_luna_terra_sol_by_workload(monkeypatch):
    monkeypatch.delenv("AGROAI_GPT56_SOL_MODEL", raising=False)
    monkeypatch.delenv("AGROAI_GPT56_TERRA_MODEL", raising=False)
    monkeypatch.delenv("AGROAI_GPT56_LUNA_MODEL", raising=False)

    assert select_model("fast", "Summarize the latest field notes") == ("gpt-5.6-luna", "low")
    assert select_model("reasoning", "Compare these field records") == ("gpt-5.6-terra", "medium")
    assert select_model("deep", "Analyze the operation") == ("gpt-5.6-sol", "high")
    assert select_model("fast", "Should we irrigate this block?") == ("gpt-5.6-sol", "high")


def test_invalid_evidence_ids_are_removed_from_facts():
    decision = _decision(
        facts=[
            GroundedFact(claim="Grounded", evidence_ids=["ev-1"]),
            GroundedFact(claim="Invented source", evidence_ids=["not-real"]),
        ]
    )

    validated = validate_decision(decision, _packet(), question="What is the measured flow?")

    assert len(validated.facts) == 1
    assert validated.facts[0].evidence_ids == ["ev-1"]


def test_operational_action_is_forced_to_human_approval():
    decision = _decision(
        recommendations=[
            Recommendation(
                action="Irrigate the field based on the current measured flow.",
                priority="next",
                rationale="The flow reading is available.",
                evidence_ids=["ev-1"],
                requires_human_approval=False,
                expires_when="When the underlying telemetry changes.",
                verification="Verify the resulting meter reading.",
            )
        ]
    )

    validated = validate_decision(decision, _packet(), question="Review irrigation readiness")

    assert validated.recommendations[0].requires_human_approval is True


def test_unsupported_numeric_recommendation_is_dropped():
    decision = _decision(
        recommendations=[
            Recommendation(
                action="Run irrigation for 45 minutes.",
                priority="now",
                rationale="This duration is appropriate.",
                evidence_ids=["ev-1"],
                requires_human_approval=True,
                expires_when="After execution.",
                verification="Confirm the meter reading.",
            )
        ]
    )

    validated = validate_decision(decision, _packet(), question="What should I do?")

    assert validated.recommendations == []


def test_observed_flow_number_cannot_be_reinterpreted_as_runtime():
    decision = _decision(
        recommendations=[
            Recommendation(
                action="Irrigate for 120 minutes.",
                priority="now",
                rationale="A flow reading exists.",
                evidence_ids=["ev-1"],
                requires_human_approval=True,
                expires_when="When telemetry changes.",
                verification="Verify the resulting meter reading.",
            )
        ]
    )

    assert validate_decision(decision, _packet(), question="Review irrigation").recommendations == []


def test_model_confidence_cannot_exceed_grounding_confidence():
    validated = validate_decision(_decision(), _packet(), question="What is the measured flow?")

    assert validated.confidence.score == 0.82
    assert validated.confidence.level == "high"

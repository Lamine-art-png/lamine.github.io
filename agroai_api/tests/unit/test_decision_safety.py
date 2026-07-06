from types import SimpleNamespace

from app.services.decision_safety import evaluate_decision_safety


def _context(*, evidence=None, citations=None, missing=None):
    return SimpleNamespace(
        evidence=list(evidence or []),
        citations=list(citations or []),
        missing_data=list(missing or []),
    )


def test_sample_mode_blocks_operational_decision_even_with_recommendation():
    context = _context(
        evidence=[
            {
                "type": "recommendation_recent",
                "duration_min": 45,
                "volume_m3": 120,
                "meta_data": {"operational_use": True},
            }
        ],
        citations=[{"id": "citation-1"}],
    )
    envelope = evaluate_decision_safety(
        task="irrigation_plan",
        question="How much water should I apply?",
        answer="Apply 120 m3 for 45 minutes.",
        context=context,
        sample_mode=True,
    )
    assert envelope.status == "blocked"
    assert envelope.execution_candidate is False
    assert any("sample" in reason for reason in envelope.reasons)


def test_unsupported_numeric_claim_blocks_operational_decision():
    context = _context(
        evidence=[
            {
                "type": "recommendation_recent",
                "duration_min": 45,
                "volume_m3": 120,
                "meta_data": {"operational_use": True},
            }
        ],
        citations=[{"id": "citation-1"}],
    )
    envelope = evaluate_decision_safety(
        task="irrigation_plan",
        question="How much water should I apply?",
        answer="Apply 250 m3 for 45 minutes.",
        context=context,
        sample_mode=False,
    )
    assert envelope.status == "blocked"
    assert envelope.execution_candidate is False
    assert any(claim.status == "unsupported" for claim in envelope.claims)


def test_missing_evidence_blocks_operational_decision():
    context = _context(
        evidence=[
            {
                "type": "recommendation_recent",
                "duration_min": 45,
                "volume_m3": 120,
                "meta_data": {"operational_use": True},
            }
        ],
        citations=[{"id": "citation-1"}],
        missing=["confirmed flow meter evidence"],
    )
    envelope = evaluate_decision_safety(
        task="irrigation_plan",
        question="Irrigate now?",
        answer="Apply 120 m3 for 45 minutes.",
        context=context,
        sample_mode=False,
    )
    assert envelope.status == "blocked"
    assert "confirmed flow meter evidence" in envelope.missing_requirements


def test_live_supported_recommendation_becomes_approval_required_not_auto_execution():
    context = _context(
        evidence=[
            {
                "type": "recommendation_recent",
                "duration_min": 45,
                "volume_m3": 120,
                "confidence": 0.82,
                "meta_data": {"operational_use": True},
            }
        ],
        citations=[{"id": "citation-1", "source": "recommendation_record"}],
    )
    envelope = evaluate_decision_safety(
        task="irrigation_plan",
        question="How much water should I apply?",
        answer="Apply 120 m3 for 45 minutes with confidence 0.82.",
        context=context,
        sample_mode=False,
    )
    assert envelope.status == "approval_required"
    assert envelope.execution_candidate is True
    assert envelope.approval_required is True


def test_non_operational_chat_remains_advisory():
    context = _context(evidence=[{"type": "workspace", "name": "North Farm"}])
    envelope = evaluate_decision_safety(
        task="chat",
        question="Summarize what you know about this workspace.",
        answer="The workspace is called North Farm.",
        context=context,
        sample_mode=False,
    )
    assert envelope.status == "advisory"
    assert envelope.execution_candidate is False

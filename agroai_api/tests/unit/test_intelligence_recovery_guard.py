from app.schemas.ai import EvidenceContext
from app.services.intelligence_grounding import build_intelligence_grounding
from app.services.intelligence_hardening import enrich_grounding_packet, sanitize_customer_answer


def _packet():
    context = EvidenceContext(
        organization_id="org-1",
        workspace_id="ws-1",
        block_id="field-1",
        evidence=[{
            "id": "meter-1",
            "type": "meter_reading",
            "block_id": "field-1",
            "summary": "Measured flow is 120 gpm in Zone 4.",
            "value_json": {"flow_rate_gpm": 120},
            "quality_status": "verified",
            "occurred_at": "2026-08-21T20:00:00Z",
        }],
    )
    return enrich_grounding_packet(build_intelligence_grounding(context, field_id="field-1"), context)


def test_recovery_model_cannot_issue_non_numeric_physical_instruction():
    answer, removed = sanitize_customer_answer(
        "Start irrigation now.",
        _packet(),
        question="What should I do?",
    )
    assert "Start irrigation" not in answer
    assert removed == {"operational_instruction"}
    assert "withheld an operational instruction" in answer


def test_recovery_model_cannot_issue_negative_operational_instruction():
    answer, removed = sanitize_customer_answer(
        "Do not irrigate this block today.",
        _packet(),
        question="Should I irrigate?",
    )
    assert "Do not irrigate" not in answer
    assert removed == {"operational_instruction"}


def test_recovery_model_can_report_measurement_without_issuing_action():
    answer, removed = sanitize_customer_answer(
        "The measured flow is 120 gpm.",
        _packet(),
        question="What is the measured flow?",
    )
    assert answer == "The measured flow is 120 gpm."
    assert removed == set()


def test_entity_identifier_is_not_treated_as_operating_quantity():
    answer, removed = sanitize_customer_answer(
        "The current evidence refers to Zone 4.",
        _packet(),
        question="Which zone does the evidence refer to?",
    )
    assert answer == "The current evidence refers to Zone 4."
    assert removed == set()


def test_operating_duration_is_still_rejected_even_with_zone_identifier():
    answer, removed = sanitize_customer_answer(
        "The analysis proposes Zone 4 for 20 minutes.",
        _packet(),
        question="Summarize the proposed operating duration.",
    )
    assert "20" not in answer
    assert "20" in removed

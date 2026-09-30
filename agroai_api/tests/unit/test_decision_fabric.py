from __future__ import annotations

import json

from app.services import decision_fabric
from app.services.decision_fabric import DecisionAdvisory


def _configure(monkeypatch, *, mode: str = "assist"):
    monkeypatch.setenv("AGROAI_DECISION_MODEL_ENABLED", "true")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_MODE", mode)
    monkeypatch.setenv("AGROAI_DECISION_MODEL_API_KEY", "unit-test-key")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_BASE_URL", "https://decision.example.test")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_MODEL", "bounded-test-model")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_TIMEOUT_SECONDS", "1.0")


def _advisory(**overrides):
    values = {
        "route": "collect_evidence",
        "route_confidence": 0.94,
        "urgency_score": 0.8,
        "urgency_confidence": 0.9,
        "needs_human_review": 0.88,
        "data_sufficient": 0.3,
        "should_act_now": 0.82,
    }
    values.update(overrides)
    return DecisionAdvisory(**values)


def test_surface_assessment_strips_identifiers_and_parses_typed_response(monkeypatch):
    _configure(monkeypatch)
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answers": {
                    "route": {"type": "choice", "choice": "review", "confidence": 0.96},
                    "urgency": {"type": "score", "score": 2.4, "confidence": 0.91},
                    "needs_human_review": {"type": "noul", "noul": 0.9},
                    "data_sufficient": {"type": "noul", "noul": 0.35},
                    "should_act_now": {"type": "noul", "noul": 0.8},
                }
            }

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["payload"] = kwargs["json"]
        return Response()

    monkeypatch.setattr(decision_fabric.httpx, "post", fake_post)
    result = decision_fabric.assess_surface(
        "generic_intelligence",
        {
            "tenant_id": "tenant-secret",
            "task": "field_diagnosis",
            "nested": {
                "email": "operator@example.com",
                "api_key": "do-not-send",
                "field_id": "field-secret",
                "safe_count": 3,
            },
        },
    )

    assert result is not None
    assert result.route == "review"
    assert abs(result.urgency_score - 0.8) < 1e-9
    outbound = json.loads(seen["payload"]["state"])
    serialized = seen["payload"]["state"]
    assert seen["url"].endswith("/v1/systemone")
    assert "tenant-secret" not in serialized
    assert "operator@example.com" not in serialized
    assert "do-not-send" not in serialized
    assert "field-secret" not in serialized
    assert outbound["nested"]["safe_count"] == 3


def test_grounding_state_never_sends_raw_question_or_tenant_ids():
    class Row:
        def __init__(self, status):
            self.status = status

    class Packet:
        organization_id = "org-secret"
        workspace_id = "workspace-secret"
        field_id = "field-secret"
        observed_facts = [object(), object()]
        derived_context = [object()]
        unknowns = ["missing controller history"]
        conflicts = [object()]
        science_checks = [Row("computed"), Row("not_computable")]
        source_health = {}
        grounding_confidence = 0.74
        decision_constraints = []

    state = decision_fabric.grounding_state(
        Packet(),
        task="irrigation_recommendation",
        question="Irrigate Secret Ranch tonight and email operator@example.com",
    )
    serialized = json.dumps(state)
    assert "org-secret" not in serialized
    assert "workspace-secret" not in serialized
    assert "field-secret" not in serialized
    assert "Secret Ranch" not in serialized
    assert "operator@example.com" not in serialized
    assert state["observed_fact_count"] == 2
    assert state["conflict_count"] == 1
    assert state["intent"]["physical_or_operational_action"] is True
    assert state["intent"]["external_or_commercial_action"] is True


def test_assist_grounding_advisory_only_adds_caution(monkeypatch):
    _configure(monkeypatch, mode="assist")
    monkeypatch.setattr(decision_fabric, "assess_surface", lambda *args, **kwargs: _advisory())

    class Packet:
        observed_facts = ["fact"]
        derived_context = []
        unknowns = ["missing"]
        conflicts = []
        science_checks = []
        source_health = {}
        grounding_confidence = 0.4
        decision_constraints = ["existing hard constraint"]

    packet = Packet()
    advisory = decision_fabric.attach_grounding_advisory(
        packet,
        task="decision",
        question="What should we do?",
    )

    assert advisory is not None
    assert packet.observed_facts == ["fact"]
    assert "decision_routing" not in packet.source_health
    assert "existing hard constraint" in packet.decision_constraints
    assert any("more evidence" in item.lower() for item in packet.decision_constraints)
    assert any("human review" in item.lower() for item in packet.decision_constraints)


def test_field_assist_can_only_increase_review_caution(monkeypatch):
    _configure(monkeypatch, mode="assist")
    advisory = _advisory()
    assert decision_fabric.field_requires_review(advisory) is True
    follow_up = decision_fabric.safe_field_follow_up(advisory)
    assert follow_up is not None
    assert "evidence" in follow_up.lower()
    assert "irrigate" not in follow_up.lower()
    assert "apply" not in follow_up.lower()


def test_shadow_mode_does_not_change_field_semantics(monkeypatch):
    _configure(monkeypatch, mode="shadow")
    advisory = _advisory()
    assert decision_fabric.field_requires_review(advisory) is False
    assert decision_fabric.safe_field_follow_up(advisory) is None


def test_casual_chat_skips_decision_fabric():
    assert decision_fabric.should_invoke("chat", "hello") is False
    assert decision_fabric.should_invoke("chat", "What needs attention in my field?") is True
    assert decision_fabric.should_invoke("ui_translation", "Translate this") is False


def test_market_state_contains_only_qualitative_or_presence_signals():
    state = decision_fabric.market_state(
        {
            "data_health": {"status": "degraded"},
            "warnings": ["stale"],
            "missing_fields": ["cost"],
            "projected_margin": "123456.78",
            "exposed_percent": "62.5",
            "contracted_percent": "37.5",
            "commodity": "Secret Specialty Crop",
        },
        {"revenue:secret": "999999"},
        question="What matters?",
    )
    serialized = json.dumps(state)
    assert "123456.78" not in serialized
    assert "62.5" not in serialized
    assert "999999" not in serialized
    assert "Secret Specialty Crop" not in serialized
    assert state["has_projected_margin"] is True
    assert state["evidence_value_count"] == 1


def test_shadow_mode_observes_without_influencing_model_context(monkeypatch):
    _configure(monkeypatch, mode="shadow")
    advisory = _advisory()

    class Packet:
        observed_facts = ["fact"]
        derived_context = []
        unknowns = []
        conflicts = []
        science_checks = []
        source_health = {}
        grounding_confidence = 0.9
        decision_constraints = ["hard rule"]

    monkeypatch.setattr(decision_fabric, "assess_surface", lambda *args, **kwargs: advisory)
    packet = Packet()
    result = decision_fabric.attach_grounding_advisory(
        packet,
        task="decision",
        question="What should we do?",
    )

    assert result is advisory
    assert "decision_routing" not in packet.source_health
    assert packet.decision_constraints == ["hard rule"]
    assert decision_fabric.advisory_prompt(advisory) == ""
    assert decision_fabric.advisory_context(advisory) is None


def test_evidence_context_exposes_only_modality_presence_not_uploaded_content():
    class Context:
        evidence = [
            {
                "type": "uploaded_file",
                "source_type": "image/jpeg",
                "filename": "Secret Field.jpg",
                "parsed_preview": "Private crop note",
            },
            {"type": "telemetry_recent", "records": [{"value": 123}]},
        ]
        missing_data = []
        citations = []

    state = decision_fabric.evidence_context_state(
        Context(),
        task="field_diagnosis",
        question="What do you see?",
    )
    serialized = json.dumps(state)
    assert state["modalities"]["has_visual_evidence"] is True
    assert state["modalities"]["has_telemetry_evidence"] is True
    assert "Secret Field.jpg" not in serialized
    assert "Private crop note" not in serialized
    assert "123" not in serialized

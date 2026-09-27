from __future__ import annotations

import json

from app.services import decision_model
from app.services.decision_model import (
    CommandCenterAssessment,
    apply_command_center_assessment,
    assess_command_center,
)


def _state():
    return {
        "status": "ok",
        "workspace_id": "workspace-internal-id",
        "operating_status": "attention",
        "today_priority": {
            "title": "North Ranch low pressure",
            "reason": "Check filter",
            "field": "North Ranch",
            "risk": "high",
            "recommended_action": "Inspect filter",
        },
        "field_queue": [
            {
                "field_id": "internal-field-a",
                "field_name": "North Ranch",
                "priority": "high",
                "status": "needs_attention",
                "issue": "Low pressure after irrigation",
                "recommended_action": "Inspect filter and valve",
                "latest_signal": "Pressure fell below normal",
                "missing_evidence": [],
                "next_operator_task": "Inspect filter",
            },
            {
                "field_id": "internal-field-b",
                "field_name": "South Ranch",
                "priority": "high",
                "status": "needs_attention",
                "issue": "Possible flow mismatch",
                "recommended_action": "Compare meter and controller",
                "latest_signal": "Meter variance reported",
                "missing_evidence": ["meter photo"],
                "next_operator_task": "Verify meter",
            },
            {
                "field_id": "internal-field-c",
                "field_name": "East Ranch",
                "priority": "medium",
                "status": "missing_evidence",
                "issue": "Missing recent observation",
                "recommended_action": "Collect field observation",
                "latest_signal": "No recent observation",
                "missing_evidence": ["field note"],
                "next_operator_task": "Add field note",
            },
        ],
        "operator_tasks": [],
        "missing_evidence": ["meter photo"],
        "recent_signals": [{"type": "flow"}],
    }


def _configure(monkeypatch):
    monkeypatch.setenv("AGROAI_DECISION_MODEL_ENABLED", "true")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_MODE", "shadow")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_API_KEY", "unit-test-value")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_BASE_URL", "https://decision.example.test")
    monkeypatch.setenv("AGROAI_DECISION_MODEL_MODEL", "test-decision-model")


def test_system_one_request_redacts_identifiers_and_keeps_operating_signal(monkeypatch):
    _configure(monkeypatch)
    config = decision_model.decision_model_config()
    request = decision_model._system_one_request(_state(), config)
    assert request is not None
    state = json.loads(request["state"])

    serialized = request["state"]
    assert "workspace-internal-id" not in serialized
    assert "internal-field-a" not in serialized
    assert "North Ranch" not in serialized
    assert "Low pressure after irrigation" in serialized
    assert state["candidates"][0]["ref"] == "item_1"
    assert request["model"] == "test-decision-model"
    assert set(request["questions"]) == {
        "focus_item",
        "urgency",
        "needs_human_review",
        "data_sufficient",
        "should_act_now",
    }


def test_assessment_parses_typed_response(monkeypatch):
    _configure(monkeypatch)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "test-model",
                "answers": {
                    "focus_item": {"type": "choice", "choice": "item_2", "confidence": 0.93},
                    "urgency": {"type": "score", "score": 2.4, "confidence": 0.88},
                    "needs_human_review": {"type": "noul", "noul": 0.91},
                    "data_sufficient": {"type": "noul", "noul": 0.72},
                    "should_act_now": {"type": "noul", "noul": 0.84},
                },
            }

    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return Response()

    monkeypatch.setattr(decision_model.httpx, "post", fake_post)
    assessment = assess_command_center(_state())

    assert assessment is not None
    assert assessment.focus_ref == "item_2"
    assert assessment.focus_confidence == 0.93
    assert assessment.urgency_score == 0.8\n    assert assessment.needs_human_review == 0.91
    assert seen["url"].endswith("/v1/systemone")


def test_assist_only_reorders_within_highest_deterministic_priority():
    state = _state()
    assessment = CommandCenterAssessment(
        focus_ref="item_2",
        focus_confidence=0.96,
        urgency_score=0.8,
        urgency_confidence=0.9,
        needs_human_review=0.9,
        data_sufficient=0.8,
        should_act_now=0.9,
    )
    updated = apply_command_center_assessment(state, assessment, min_confidence=0.85)
    assert updated["field_queue"][0]["field_name"] == "South Ranch"
    assert state["field_queue"][0]["field_name"] == "North Ranch"

    lower_priority = CommandCenterAssessment(
        focus_ref="item_3",
        focus_confidence=0.99,
        urgency_score=0.4,
        urgency_confidence=0.9,
        needs_human_review=0.1,
        data_sufficient=0.9,
        should_act_now=0.4,
    )
    unchanged = apply_command_center_assessment(state, lower_priority, min_confidence=0.85)
    assert unchanged is state


def test_low_confidence_cannot_change_command_center():
    state = _state()
    assessment = CommandCenterAssessment(
        focus_ref="item_2",
        focus_confidence=0.5,
        urgency_score=0.8,
        urgency_confidence=0.4,
        needs_human_review=0.8,
        data_sufficient=0.7,
        should_act_now=0.8,
    )
    assert apply_command_center_assessment(state, assessment, min_confidence=0.85) is state

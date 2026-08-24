from app.api.v1.ai_stable import _decision_memory_failure_response, _grounding_failure_response
from app.api.v1.brain import BrainRunRequest


def _payload():
    return BrainRunRequest(
        task="decision",
        question="Should I irrigate this field?",
        workspace_id="ws-1",
        field_id="field-1",
        preferred_language="en",
    )


def _bundle():
    return {"sample_mode": False, "commercial_intelligence": {"profile": "advanced"}}


def test_grounding_failure_response_is_fail_closed_and_action_free():
    response = _grounding_failure_response(_payload(), _bundle(), "deep")
    assert response["status"] == "unavailable"
    assert response["confidence"] == "low"
    assert response["result"]["error"] == "intelligence_grounding_unavailable"
    assert response["result"]["recommendations"] == []
    assert response["result"]["next_actions"] == []
    assert "No recommendation or operating number was generated" in response["result"]["answer"]
    assert response["reasoning_contract"] == "evidence_graph_v1_fail_closed"


def test_memory_failure_response_withholds_operational_recommendations():
    response = _decision_memory_failure_response(_payload(), _bundle(), "deep")
    assert response["status"] == "unavailable"
    assert response["confidence"] == "low"
    assert response["result"]["error"] == "decision_memory_unavailable"
    assert response["result"]["recommendations"] == []
    assert response["result"]["next_actions"] == []
    assert "No operational recommendation was released" in response["result"]["answer"]
    assert response["reasoning_contract"] == "evidence_graph_v1_memory_fail_closed"

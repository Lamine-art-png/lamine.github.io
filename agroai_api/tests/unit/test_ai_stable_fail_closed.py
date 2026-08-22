from app.api.v1.ai_stable import _grounding_failure_response
from app.api.v1.brain import BrainRunRequest


def test_grounding_failure_response_is_fail_closed_and_action_free():
    payload = BrainRunRequest(
        task="decision",
        question="Should I irrigate this field?",
        workspace_id="ws-1",
        field_id="field-1",
        preferred_language="en",
    )
    bundle = {
        "sample_mode": False,
        "commercial_intelligence": {"profile": "advanced"},
    }
    response = _grounding_failure_response(payload, bundle, "deep")
    assert response["status"] == "unavailable"
    assert response["confidence"] == "low"
    assert response["result"]["error"] == "intelligence_grounding_unavailable"
    assert response["result"]["recommendations"] == []
    assert response["result"]["next_actions"] == []
    assert "No recommendation or operating number was generated" in response["result"]["answer"]
    assert response["reasoning_contract"] == "evidence_graph_v1_fail_closed"

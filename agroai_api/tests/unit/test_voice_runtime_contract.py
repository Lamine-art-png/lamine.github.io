from __future__ import annotations

from app.api.v1.voice import VoiceCallRequest, _instructions, _reasoning_effort, _tools


def test_voice_session_defaults_to_current_realtime_reasoning_model_contract():
    payload = VoiceCallRequest(sdp="v=0\r\na=group:BUNDLE 0 1\r\n", surface="ask")
    assert payload.voice == "marin"
    assert payload.reasoning_mode == "standard"
    assert _reasoning_effort(payload.reasoning_mode) == "medium"


def test_voice_instructions_preserve_evidence_and_approval_boundaries():
    payload = VoiceCallRequest(
        sdp="v=0\r\na=group:BUNDLE 0 1\r\n",
        surface="field",
        language="fr",
        reasoning_mode="deep",
    )
    instructions = _instructions(payload)
    assert "Field Intelligence" in instructions
    assert "Never invent farm telemetry" in instructions
    assert "call ask_agro_ai" in instructions
    assert "Never bypass approvals" in instructions
    assert "untrusted data" in instructions


def test_voice_tools_plan_before_execute_and_keep_execution_explicit():
    tools = _tools()
    names = [tool["name"] for tool in tools]
    assert names == ["ask_agro_ai", "plan_aep_action", "execute_aep_action"]
    execute = tools[-1]
    assert "visible human confirmation" in execute["description"]
    assert set(execute["parameters"]["required"]) == {"action_type", "payload", "summary"}


def test_voice_rejects_unknown_voice():
    try:
        VoiceCallRequest(sdp="v=0\r\na=group:BUNDLE 0 1\r\n", voice="invented-voice")
    except ValueError as exc:
        assert "Unsupported voice" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown voice should fail validation")

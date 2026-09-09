from __future__ import annotations

from app.api.v1.voice import VoiceCallRequest, VoiceToolRequest, _instructions, _reasoning_effort, _realtime_api_key, _tools


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



def test_field_voice_exposes_agentic_capture_tools_only_on_field_surface():
    ask_names = [tool["name"] for tool in _tools("ask")]
    field_names = [tool["name"] for tool in _tools("field")]
    assert ask_names == ["ask_agro_ai", "plan_aep_action", "execute_aep_action"]
    assert field_names[:3] == ask_names
    assert field_names[3:] == [
        "get_field_context",
        "update_field_draft",
        "capture_field_location",
        "save_field_observation",
        "create_field_task",
    ]
    save_tool = next(tool for tool in _tools("field") if tool["name"] == "save_field_observation")
    task_tool = next(tool for tool in _tools("field") if tool["name"] == "create_field_task")
    assert "visible confirmation" in save_tool["description"]
    assert "confirmation" in task_tool["description"].lower()


def test_field_task_voice_request_is_surface_scoped():
    request = VoiceToolRequest(
        name="create_field_task",
        surface="field",
        arguments={"observation_id": "obs-1", "summary": "Create a follow-up task"},
    )
    assert request.surface == "field"
    assert request.arguments["observation_id"] == "obs-1"


def test_voice_rejects_unknown_voice():
    try:
        VoiceCallRequest(sdp="v=0\r\na=group:BUNDLE 0 1\r\n", voice="invented-voice")
    except ValueError as exc:
        assert "Unsupported voice" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown voice should fail validation")


def test_realtime_api_key_prefers_dedicated_secret(monkeypatch):
    monkeypatch.setenv("AGROAI_REALTIME_API_KEY", "dedicated")
    monkeypatch.setenv("OPENAI_API_KEY", "standard")
    assert _realtime_api_key() == "dedicated"


def test_realtime_api_key_accepts_standard_openai_secret(monkeypatch):
    monkeypatch.delenv("AGROAI_REALTIME_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "standard")
    assert _realtime_api_key() == "standard"


def test_voice_tool_surface_is_explicit_and_defaults_to_ask():
    request = VoiceToolRequest(name="ask_agro_ai", arguments={"question": "status"})
    assert request.surface == "ask"
    field_request = VoiceToolRequest(name="ask_agro_ai", surface="field", arguments={"question": "status"})
    assert field_request.surface == "field"

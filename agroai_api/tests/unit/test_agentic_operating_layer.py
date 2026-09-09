from app.api.v1.agentic_actions import APPROVAL_REQUIRED, plan_actions


def _plan(text: str, answer: str = "Grounded AGRO-AI answer"):
    return plan_actions(text, workspace_id="ws-1", answer=answer, uploaded_evidence=[])


def _by_type(actions, action_type):
    return next(item for item in actions if item["action_type"] == action_type)


def test_normal_question_does_not_manufacture_actions():
    assert _plan("What is happening with irrigation this week?") == []


def test_create_operation_is_safe_auto_executable_when_name_is_explicit():
    action = _by_type(
        _plan("Create a new operation called Sunrise Ranch for almonds in Fresno."),
        "create_operation",
    )
    assert action["status"] == "ready"
    assert action["auto_execute"] is True
    assert action["approval_required"] is False
    assert action["payload"]["name"] == "Sunrise Ranch"
    assert action["payload"]["crop"].lower() == "almonds"
    assert "fresno" in action["payload"]["region"].lower()


def test_powerpoint_request_creates_real_workspace_artifact_action():
    action = _by_type(
        _plan("Build a PowerPoint presentation from this analysis."),
        "generate_workspace_artifact",
    )
    assert action["payload"]["format"] == "pptx"
    assert action["auto_execute"] is True


def test_source_refresh_is_safe_internal_action():
    action = _by_type(_plan("Pull the latest data from our connected systems."), "sync_connected_sources")
    assert action["auto_execute"] is True
    assert action["approval_required"] is False


def test_external_email_stays_confirmation_gated():
    action = _by_type(
        _plan("Send an email to manager@example.com with this operating update."),
        "send_email",
    )
    assert action["approval_required"] is True
    assert action["auto_execute"] is False
    assert "send_email" in APPROVAL_REQUIRED


def test_email_draft_is_internal_and_does_not_send():
    action = _by_type(
        _plan("Draft an email to manager@example.com about today's irrigation issue."),
        "draft_email",
    )
    assert action["approval_required"] is False
    assert action["auto_execute"] is True

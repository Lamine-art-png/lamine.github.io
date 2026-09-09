from app.core.config import settings
from app.services.agentic_plan_tokens import sign_action_plan, verify_action_plan


def test_signed_action_plan_preserves_exact_payload(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret-key-with-more-than-thirty-two-characters")
    action = {
        "id": "act-1",
        "action_type": "create_operation",
        "payload": {
            "name": "Sunrise Almond Ranch",
            "region": "Fresno, California",
            "crop": "almonds",
        },
        "approval_required": False,
        "title": "Create operation: Sunrise Almond Ranch",
    }
    token = sign_action_plan(
        organization_id="org-1",
        user_id="user-1",
        workspace_id="ws-1",
        action=action,
    )
    decoded = verify_action_plan(token, organization_id="org-1", user_id="user-1")
    assert decoded["action_type"] == "create_operation"
    assert decoded["payload"]["name"] == "Sunrise Almond Ranch"
    assert decoded["payload"]["region"] == "Fresno, California"
    assert decoded["payload"]["crop"] == "almonds"

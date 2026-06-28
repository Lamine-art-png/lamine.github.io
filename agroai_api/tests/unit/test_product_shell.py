from __future__ import annotations


def _register(client, email: str = "shell@example.com"):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "strong-password",
            "name": "Shell User",
            "organization_name": "Shell Farms",
            "workspace_name": "Shell Workspace",
            "crop": "Almonds",
            "region": "California",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _body_text(payload) -> str:
    return str(payload).lower()


def test_product_plans_returns_free_professional_network(client):
    response = client.get("/v1/product/plans")
    assert response.status_code == 200
    body = response.json()
    plan_ids = {plan["id"] for plan in body["plans"]}
    assert {"free", "professional", "network"}.issubset(plan_ids)
    assert body["service_add_ons"]


def test_account_me_returns_profile_safely(client):
    headers = _register(client)
    response = client.get("/v1/account/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "shell@example.com"
    assert body["workspace"]["name"] == "Shell Workspace"
    assert body["plan"]["id"] == "free"


def test_account_security_does_not_fake_unavailable_features(client):
    headers = _register(client, "security-v2@example.com")
    response = client.get("/v1/account/security", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email_verification"]["status"] == "not_available_yet"
    assert body["two_factor"]["status"] == "not_available_yet"
    assert "enabled" not in _body_text(body)


def test_onboarding_start_update_complete_works(client):
    headers = _register(client, "onboarding@example.com")
    start = client.post("/v1/onboarding/start", headers=headers, json={"current_step": "organization"})
    assert start.status_code == 200
    update = client.patch(
        "/v1/onboarding/state",
        headers=headers,
        json={
            "current_step": "plan",
            "selected_plan": "professional",
            "organization_type": "Farm / grower",
            "acres_or_sites": "1200 acres",
            "primary_goal": "Water risk",
            "completed_steps": ["account", "organization", "scope"],
        },
    )
    assert update.status_code == 200
    assert update.json()["onboarding"]["selected_plan"] == "professional"
    complete = client.post("/v1/onboarding/complete", headers=headers)
    assert complete.status_code == 200
    assert complete.json()["onboarding"]["current_step"] == "complete"


def test_billing_summary_returns_current_plan_without_customer_debug(client):
    headers = _register(client, "billing-summary-v2@example.com")
    response = client.get("/v1/billing/summary", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_plan"]["id"] == "free"
    forbidden = ["payment_provider_configured", "setup_required", "provider_not_configured", "stripe_missing"]
    assert not any(term in _body_text(body) for term in forbidden)


def test_professional_checkout_creates_upgrade_request_if_stripe_missing(client, monkeypatch):
    headers = _register(client, "checkout-v2@example.com")
    monkeypatch.setattr("app.api.v1.product_shell.settings.STRIPE_SECRET_KEY", "", raising=False)
    response = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={"plan_id": "professional", "billing_period": "monthly"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Upgrade request received."
    assert body["request_id"]
    forbidden = ["payment_provider_configured", "setup_required", "provider_not_configured", "stripe_missing"]
    assert not any(term in _body_text(body) for term in forbidden)


def test_professional_checkout_returns_checkout_url_if_stripe_configured(client, monkeypatch):
    headers = _register(client, "checkout-live@example.com")

    class _Session:
        @staticmethod
        def create(**_kwargs):
            return {"url": "https://checkout.example/session"}

    monkeypatch.setattr("app.api.v1.product_shell.settings.STRIPE_SECRET_KEY", "sk_test_fake", raising=False)
    monkeypatch.setattr("app.api.v1.product_shell.settings.STRIPE_PRICE_ASSURANCE_MONTHLY", "price_fake", raising=False)
    monkeypatch.setattr("app.api.v1.product_shell.stripe.checkout.Session", _Session)
    response = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={"plan_id": "professional", "billing_period": "monthly"},
    )
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.example/session"


def test_support_sales_and_onboarding_requests_create_saas_requests(client):
    headers = _register(client, "requests@example.com")
    support = client.post(
        "/v1/support/ticket",
        headers=headers,
        json={"category": "integration", "subject": "Connect Dropbox", "message": "Need Dropbox evidence sync."},
    )
    assert support.status_code == 200
    sales = client.post(
        "/v1/sales/contact",
        json={"type": "sales", "subject": "Professional plan", "message": "Call us.", "email": "buyer@example.com", "company": "Buyer Co"},
    )
    assert sales.status_code == 200
    onboarding = client.post(
        "/v1/onboarding/request",
        headers=headers,
        json={"category": "onboarding", "subject": "Need setup", "message": "Help set up fields."},
    )
    assert onboarding.status_code == 200
    admin = client.get("/v1/admin/requests", headers=headers)
    assert admin.status_code == 200
    types = {row["type"] for row in admin.json()["requests"]}
    assert {"integration", "onboarding"}.issubset(types)


def test_admin_can_update_request_status(client):
    headers = _register(client, "admin-update@example.com")
    created = client.post(
        "/v1/support/ticket",
        headers=headers,
        json={"category": "support", "subject": "Need help", "message": "Please help."},
    )
    request_id = created.json()["request_id"]
    response = client.patch(
        f"/v1/admin/requests/{request_id}",
        headers=headers,
        json={"status": "in_progress", "priority": "high"},
    )
    assert response.status_code == 200
    assert response.json()["request"]["status"] == "in_progress"
    assert response.json()["request"]["priority"] == "high"


def test_conversation_create_list_get_message_and_delete(client):
    headers = _register(client, "chat-v2@example.com")
    created = client.post(
        "/v1/conversations",
        headers=headers,
        json={"title": "Daily ops", "message": "What needs attention today?"},
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation"]["id"]
    assert created.json()["messages"][-1]["artifacts"][0]["intent"] == "operator_checklist"
    listed = client.get("/v1/conversations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["conversations"]
    message = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Generate a water risk brief."},
    )
    assert message.status_code == 200
    assert message.json()["message"]["artifacts"][0]["intent"] == "water_risk_brief"
    fetched = client.get(f"/v1/conversations/{conversation_id}", headers=headers)
    assert fetched.status_code == 200
    deleted = client.delete(f"/v1/conversations/{conversation_id}", headers=headers)
    assert deleted.status_code == 200


def test_report_and_operator_intents_return_actions(client):
    headers = _register(client, "intents@example.com")
    report = client.post("/v1/conversations", headers=headers, json={"message": "Prepare a compliance packet PDF."})
    assert report.status_code == 200
    report_actions = report.json()["messages"][-1]["artifacts"][0]["actions"]
    assert any(action["type"] == "generate_report" for action in report_actions)
    operator = client.post("/v1/conversations", headers=headers, json={"message": "Create an operator checklist."})
    operator_actions = operator.json()["messages"][-1]["artifacts"][0]["actions"]
    assert any(action["type"] == "create_task" for action in operator_actions)


def test_customer_responses_do_not_expose_debug_model_or_provider_language(client):
    headers = _register(client, "redaction-v2@example.com")
    responses = [
        client.get("/v1/app/shell", headers=headers),
        client.get("/v1/billing/summary", headers=headers),
        client.get("/v1/account/security", headers=headers),
        client.post("/v1/billing/checkout", headers=headers, json={"plan_id": "professional", "billing_period": "monthly"}),
        client.post("/v1/conversations", headers=headers, json={"message": "What evidence is missing?"}),
    ]
    combined = _body_text([response.json() for response in responses])
    forbidden = [
        "payment_provider_configured",
        "setup_required",
        "provider_not_configured",
        "openai_compatible",
        "fallback",
        "debug",
        "model",
        "z-ai",
        "nemotron",
        "sk_",
        "oauth_code",
        "client_secret",
    ]
    assert not any(term in combined for term in forbidden)

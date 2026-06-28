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


def test_app_shell_returns_nav_account_plan_and_support(client):
    headers = _register(client)
    response = client.get("/v1/app/shell", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "shell@example.com"
    assert body["workspace"]["name"] == "Shell Workspace"
    assert body["plan"]["id"] == "free"
    assert any(section["section"] == "Operate" for section in body["nav"])
    assert body["support"]["options"]


def test_billing_summary_returns_current_plan(client):
    headers = _register(client, "billing-summary@example.com")
    response = client.get("/v1/billing/summary", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_plan"]["id"] == "free"
    assert body["monthly_price"] == "$0"
    assert "payment_provider_configured" in body


def test_billing_checkout_does_not_fake_payment_when_provider_absent(client, monkeypatch):
    headers = _register(client, "checkout@example.com")
    monkeypatch.setattr("app.api.v1.product_shell.settings.STRIPE_SECRET_KEY", "", raising=False)
    response = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={"plan_id": "professional", "billing_period": "monthly"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "payment_provider_setup_required"
    assert "succeeded" not in _body_text(body)


def test_account_security_returns_safe_verification_state(client):
    headers = _register(client, "security@example.com")
    response = client.get("/v1/account/security", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email_verified"] is False
    assert body["two_factor_enabled"] is False
    assert body["login_methods"] == ["password"]


def test_support_options_returns_product_support_surfaces(client):
    response = client.get("/v1/support/options")
    assert response.status_code == 200
    option_ids = {option["id"] for option in response.json()["options"]}
    assert {"contact_support", "request_integration", "book_onboarding", "network_sales"}.issubset(option_ids)


def test_product_shell_does_not_expose_secrets_or_oauth_codes(client):
    headers = _register(client, "redaction-shell@example.com")
    responses = [
        client.get("/v1/product/plans"),
        client.get("/v1/app/shell", headers=headers),
        client.get("/v1/billing/summary", headers=headers),
        client.get("/v1/account/security", headers=headers),
        client.get("/v1/support/options"),
    ]
    combined = _body_text([response.json() for response in responses])
    assert "sk_" not in combined
    assert "api_key" not in combined
    assert "oauth_code" not in combined
    assert "client_secret" not in combined

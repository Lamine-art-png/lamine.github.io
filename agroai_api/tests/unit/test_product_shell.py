from datetime import datetime

from app.models.saas import Organization, User


def _register_and_login(client, db, email: str = "shell@example.com"):
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
    user = db.query(User).filter(User.email == email).first()
    user.email_verification_status = "verified"
    user.email_verified_at = datetime.utcnow()
    db.commit()
    login = client.post("/v1/auth/login", json={"email": email, "password": "strong-password"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _body_text(payload) -> str:
    return str(payload).lower()


def test_product_plans_returns_five_tiers(client):
    response = client.get("/v1/product/plans")
    assert response.status_code == 200
    body = response.json()
    plan_ids = {plan["id"] for plan in body["plans"]}
    assert {"free", "professional", "team", "network", "enterprise"}.issubset(plan_ids)
    assert body["service_add_ons"]


def test_account_me_returns_profile_safely(client, db):
    headers = _register_and_login(client, db)
    response = client.get("/v1/account/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "shell@example.com"
    assert body["workspace"]["name"] == "Shell Workspace"
    assert body["plan"]["id"] == "free"
    assert body["entitlements"]["plan"] == "free"


def test_account_security_returns_verification_state(client, db):
    headers = _register_and_login(client, db, "security-v21@example.com")
    response = client.get("/v1/account/security", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email_verification"]["status"] == "verified"
    assert body["two_factor"]["status"] == "not_available_yet"


def test_billing_summary_returns_current_plan_without_customer_debug(client, db):
    headers = _register_and_login(client, db, "billing-summary-v21@example.com")
    response = client.get("/v1/billing/summary", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_plan"]["id"] == "free"
    forbidden = ["payment_provider_configured", "setup_required", "provider_not_configured", "stripe_missing"]
    assert not any(term in _body_text(body) for term in forbidden)


def test_professional_checkout_fails_closed_if_stripe_missing(client, db, monkeypatch):
    headers = _register_and_login(client, db, "checkout-v21@example.com")
    monkeypatch.setattr("app.api.v1.billing.settings.STRIPE_SECRET_KEY", "", raising=False)
    monkeypatch.setattr("app.api.v1.billing.settings.STRIPE_PRICE_PRO_MONTHLY", "price_fake", raising=False)
    response = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={"plan_id": "professional", "billing_period": "monthly"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "stripe_not_configured"


def test_professional_checkout_returns_checkout_url_if_stripe_configured(client, db, monkeypatch):
    headers = _register_and_login(client, db, "checkout-live@example.com")

    class _Customer:
        @staticmethod
        def create(**_kwargs):
            return {"id": "cus_fake"}

    class _Session:
        @staticmethod
        def create(**_kwargs):
            return {"url": "https://checkout.example/session"}

    monkeypatch.setattr("app.api.v1.billing.settings.STRIPE_SECRET_KEY", "sk_test_fake", raising=False)
    monkeypatch.setattr("app.api.v1.billing.settings.STRIPE_PRICE_PRO_MONTHLY", "price_fake", raising=False)
    monkeypatch.setattr("app.api.v1.billing.stripe.Customer", _Customer)
    monkeypatch.setattr("app.api.v1.billing.stripe.checkout.Session", _Session)
    response = client.post(
        "/v1/billing/checkout",
        headers=headers,
        json={"plan_id": "professional", "billing_period": "monthly"},
    )
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.example/session"


def test_team_invites_require_team_entitlement(client, db):
    headers = _register_and_login(client, db, "team-lock@example.com")
    response = client.post("/v1/team/invitations", headers=headers, json={"email": "teammate@example.com", "role": "manager"})
    assert response.status_code == 402
    assert response.json()["detail"]["recommended_plan"] == "team"


def test_team_plan_unlocks_team_invites(client, db):
    headers = _register_and_login(client, db, "team-open@example.com")
    org = db.query(Organization).filter(Organization.name == "Shell Farms").order_by(Organization.created_at.desc()).first()
    org.plan = "team"
    org.subscription_status = "active"
    db.commit()
    response = client.post("/v1/team/invitations", headers=headers, json={"email": "teammate@example.com", "role": "manager"})
    assert response.status_code == 200
    invitations = client.get("/v1/team/invitations", headers=headers)
    assert invitations.status_code == 200
    assert invitations.json()["invitations"][0]["email"] == "teammate@example.com"


def test_admin_system_requires_owner_or_admin(client, db):
    headers = _register_and_login(client, db, "system-admin@example.com")
    response = client.get("/v1/admin/system", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["billing"] in {"Configured", "Needs setup"}
    assert "technical_details" in body


def test_conversation_create_list_get_message_and_delete(client, db):
    headers = _register_and_login(client, db, "chat-v21@example.com")
    created = client.post(
        "/v1/conversations",
        headers=headers,
        json={"title": "Daily ops", "message": "What needs attention today?"},
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation"]["id"]
    listed = client.get("/v1/conversations", headers=headers)
    assert listed.status_code == 200
    message = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Generate a water risk brief."},
    )
    assert message.status_code == 200
    fetched = client.get(f"/v1/conversations/{conversation_id}", headers=headers)
    assert fetched.status_code == 200
    deleted = client.delete(f"/v1/conversations/{conversation_id}", headers=headers)
    assert deleted.status_code == 200


def test_customer_responses_do_not_expose_debug_model_or_provider_language(client, db):
    headers = _register_and_login(client, db, "redaction-v21@example.com")
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
        "z-ai",
        "nemotron",
        "sk_",
        "oauth_code",
        "client_secret",
    ]
    assert not any(term in combined for term in forbidden)

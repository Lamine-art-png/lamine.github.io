from datetime import datetime

from app.models.saas import OrganizationMembership, User


def _register_account(client, email):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "strong-password",
            "name": "Auth Hot Path",
            "organization_name": "Auth Hot Path Farms",
            "workspace_name": "Evaluation workspace",
            "crop": "Grapes",
            "region": "California",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _verified_account(client, db):
    body = _register_account(client, "auth-hot-path@example.com")
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == body["current_organization"]["id"])
        .first()
    )
    membership.user.email_verification_status = "verified"
    membership.user.email_verified_at = datetime.utcnow()
    db.commit()
    return membership.user.email


def test_repeat_login_and_me_never_reseed_evaluation_context(client, db, monkeypatch):
    email = _verified_account(client, db)

    first_login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "strong-password"},
    )
    assert first_login.status_code == 200, first_login.text

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("evaluation context seeding must not run in repeat auth")

    monkeypatch.setattr("app.api.v1.auth.ensure_evaluation_context", fail_if_called)

    repeat_login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "strong-password"},
    )
    assert repeat_login.status_code == 200, repeat_login.text
    token = repeat_login.json()["access_token"]

    me = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == email


def test_portal_bootstrap_returns_first_paint_state_in_one_request(client, db):
    email = _verified_account(client, db)
    login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "strong-password"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    bootstrap = client.get(
        "/v1/auth/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bootstrap.status_code == 200, bootstrap.text
    payload = bootstrap.json()
    assert payload["user"]["email"] == email
    assert payload["current_organization"]["id"] == login.json()["current_organization"]["id"]
    assert payload["organizations"]
    assert len(payload["workspaces"]) == 1
    assert payload["workspaces"][0]["name"] == "Evaluation workspace"
    assert isinstance(payload["entitlements"], dict)
    assert "platform_developer" not in payload
    assert "portal_bootstrap_total" in bootstrap.headers.get("server-timing", "")
    assert float(bootstrap.headers["x-agroai-bootstrap-ms"]) >= 0


def test_email_verification_confirm_keeps_one_time_activation_seed(client, db, monkeypatch):
    email = "verification-activation@example.com"
    _register_account(client, email)
    user = db.query(User).filter(User.email == email).one()
    seed_calls = []

    def fake_confirm(active_db, _token):
        user.email_verification_status = "verified"
        user.email_verified_at = datetime.utcnow()
        active_db.flush()
        return user

    def capture_seed(*args, **kwargs):
        seed_calls.append((args, kwargs))
        return {}

    monkeypatch.setattr("app.api.v1.auth.confirm_verification", fake_confirm)
    monkeypatch.setattr("app.api.v1.auth.ensure_evaluation_context", capture_seed)

    response = client.post(
        "/v1/auth/email-verification/confirm",
        json={"token": "verification-test-token-20260802"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert len(seed_calls) == 1

from datetime import datetime

from app.models.saas import EmailVerificationToken, OrganizationMembership


def _verified_account(client, db):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "auth-hot-path@example.com",
            "password": "strong-password",
            "name": "Auth Hot Path",
            "organization_name": "Auth Hot Path Farms",
            "workspace_name": "Evaluation workspace",
            "crop": "Grapes",
            "region": "California",
        },
    )
    assert response.status_code == 201, response.text
    org_id = response.json()["current_organization"]["id"]
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == org_id)
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

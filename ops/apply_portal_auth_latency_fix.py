from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    if old in text:
        return text.replace(old, new)
    if new in text:
        return text
    raise RuntimeError(f"Expected source block not found: {old[:140]!r}")


auth_path = Path("agroai_api/app/api/v1/auth.py")
text = auth_path.read_text()

text = replace_once(
    text,
    "from sqlalchemy.orm import Session\n",
    "from sqlalchemy.orm import Session, joinedload\n",
)
text = replace_once(
    text,
    "    user = db.query(User).filter(User.email == email).first()\n"
    "    ip_address, user_agent = _request_metadata(request)\n",
    "    user = (\n"
    "        db.query(User)\n"
    "        .options(\n"
    "            joinedload(User.memberships).joinedload(OrganizationMembership.organization)\n"
    "        )\n"
    "        .filter(User.email == email)\n"
    "        .first()\n"
    "    )\n"
    "    membership = (\n"
    "        min(user.memberships, key=lambda item: item.created_at)\n"
    "        if user and user.memberships\n"
    "        else None\n"
    "    )\n"
    "    ip_address, user_agent = _request_metadata(request)\n",
)
text = replace_once(
    text,
    "            organization_id=user.memberships[0].organization_id if user.memberships else None,\n",
    "            organization_id=membership.organization_id if membership else None,\n",
)
text = replace_once(
    text,
    "            organization_id=user.memberships[0].organization_id if user and user.memberships else None,\n",
    "            organization_id=membership.organization_id if membership else None,\n",
)
text = replace_once(
    text,
    "    membership = (\n"
    "        db.query(OrganizationMembership)\n"
    "        .filter(OrganizationMembership.user_id == user.id)\n"
    "        .order_by(OrganizationMembership.created_at.asc())\n"
    "        .first()\n"
    "    )\n"
    "    if not membership:\n",
    "    if not membership:\n",
)
text = replace_once(
    text,
    "    ensure_evaluation_context(db, membership.organization, _first_workspace(db, membership.organization_id))\n",
    "",
)
text = replace_once(
    text,
    "@router.get(\"/me\")\n"
    "def me(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:\n"
    "    if ctx.organization:\n"
    "        ensure_evaluation_context(db, ctx.organization, _first_workspace(db, ctx.organization.id))\n"
    "        db.commit()\n\n",
    "@router.get(\"/me\")\n"
    "def me(ctx: AuthContext = Depends(get_auth_context)) -> dict:\n",
)
auth_path.write_text(text)

test_path = Path("agroai_api/tests/unit/test_auth_hot_path.py")
test_path.write_text(
    '''from datetime import datetime\n\nfrom app.models.saas import OrganizationMembership\n\n\ndef _verified_account(client, db):\n    response = client.post(\n        "/v1/auth/register",\n        json={\n            "email": "auth-hot-path@example.com",\n            "password": "strong-password",\n            "name": "Auth Hot Path",\n            "organization_name": "Auth Hot Path Farms",\n            "workspace_name": "Evaluation workspace",\n            "crop": "Grapes",\n            "region": "California",\n        },\n    )\n    assert response.status_code == 201, response.text\n    org_id = response.json()["current_organization"]["id"]\n    membership = (\n        db.query(OrganizationMembership)\n        .filter(OrganizationMembership.organization_id == org_id)\n        .first()\n    )\n    membership.user.email_verification_status = "verified"\n    membership.user.email_verified_at = datetime.utcnow()\n    db.commit()\n    return membership.user.email\n\n\ndef test_repeat_login_and_me_never_reseed_evaluation_context(client, db, monkeypatch):\n    email = _verified_account(client, db)\n\n    first_login = client.post(\n        "/v1/auth/login",\n        json={"email": email, "password": "strong-password"},\n    )\n    assert first_login.status_code == 200, first_login.text\n\n    def fail_if_called(*_args, **_kwargs):\n        raise AssertionError("evaluation context seeding must not run in repeat auth")\n\n    monkeypatch.setattr("app.api.v1.auth.ensure_evaluation_context", fail_if_called)\n\n    repeat_login = client.post(\n        "/v1/auth/login",\n        json={"email": email, "password": "strong-password"},\n    )\n    assert repeat_login.status_code == 200, repeat_login.text\n    token = repeat_login.json()["access_token"]\n\n    me = client.get(\n        "/v1/auth/me",\n        headers={"Authorization": f"Bearer {token}"},\n    )\n    assert me.status_code == 200, me.text\n    assert me.json()["user"]["email"] == email\n'''
)

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
    "            joinedload(User.memberships)\n"
    "            .joinedload(OrganizationMembership.organization)\n"
    "            .joinedload(Organization.verification_profile)\n"
    "        )\n"
    "        .filter(User.email == email)\n"
    "        .first()\n"
    "    )\n"
    "    membership = (\n"
    "        min(user.memberships, key=lambda item: item.created_at or datetime.min)\n"
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


deps_path = Path("agroai_api/app/api/deps.py")
deps = deps_path.read_text()
deps = replace_once(
    deps,
    "from sqlalchemy.orm import Session\n",
    "from sqlalchemy.orm import Session, joinedload\n",
)
deps = replace_once(
    deps,
    "def _assert_token_organization_access(payload: dict, user: User, db: Session) -> None:\n"
    "    org_id = payload.get(\"org_id\") or payload.get(\"tenant_id\")\n"
    "    if not org_id:\n"
    "        return\n"
    "    membership = (\n"
    "        db.query(OrganizationMembership)\n"
    "        .filter(OrganizationMembership.organization_id == str(org_id), OrganizationMembership.user_id == user.id)\n"
    "        .first()\n"
    "    )\n",
    "def _assert_token_organization_access(payload: dict, user: User, _db: Session) -> None:\n"
    "    org_id = payload.get(\"org_id\") or payload.get(\"tenant_id\")\n"
    "    if not org_id:\n"
    "        return\n"
    "    membership = next(\n"
    "        (item for item in user.memberships if item.organization_id == str(org_id)),\n"
    "        None,\n"
    "    )\n",
)
deps = replace_once(
    deps,
    "    user = db.get(User, user_id)\n",
    "    user = (\n"
    "        db.query(User)\n"
    "        .options(\n"
    "            joinedload(User.memberships)\n"
    "            .joinedload(OrganizationMembership.organization)\n"
    "            .joinedload(Organization.verification_profile)\n"
    "        )\n"
    "        .filter(User.id == user_id)\n"
    "        .first()\n"
    "    )\n",
)
deps = replace_once(
    deps,
    "def get_auth_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthContext:\n"
    "    require_verified_user(user)\n"
    "    membership = (\n"
    "        db.query(OrganizationMembership)\n"
    "        .filter(\n"
    "            OrganizationMembership.user_id == user.id,\n"
    "            OrganizationMembership.status == \"active\",\n"
    "        )\n"
    "        .order_by(OrganizationMembership.created_at.asc())\n"
    "        .first()\n"
    "    )\n",
    "def get_auth_context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthContext:\n"
    "    require_verified_user(user)\n"
    "    active_memberships = [item for item in user.memberships if item.status == \"active\"]\n"
    "    membership = (\n"
    "        min(active_memberships, key=lambda item: item.created_at or datetime.min)\n"
    "        if active_memberships\n"
    "        else None\n"
    "    )\n",
)
deps_path.write_text(deps)


test_path = Path("agroai_api/tests/unit/test_auth_hot_path.py")
test_path.write_text(
    '''from datetime import datetime\n\nfrom app.models.saas import OrganizationMembership\n\n\ndef _verified_account(client, db):\n    response = client.post(\n        "/v1/auth/register",\n        json={\n            "email": "auth-hot-path@example.com",\n            "password": "strong-password",\n            "name": "Auth Hot Path",\n            "organization_name": "Auth Hot Path Farms",\n            "workspace_name": "Evaluation workspace",\n            "crop": "Grapes",\n            "region": "California",\n        },\n    )\n    assert response.status_code == 201, response.text\n    org_id = response.json()["current_organization"]["id"]\n    membership = (\n        db.query(OrganizationMembership)\n        .filter(OrganizationMembership.organization_id == org_id)\n        .first()\n    )\n    membership.user.email_verification_status = "verified"\n    membership.user.email_verified_at = datetime.utcnow()\n    db.commit()\n    return membership.user.email\n\n\ndef test_repeat_login_and_me_never_reseed_evaluation_context(client, db, monkeypatch):\n    email = _verified_account(client, db)\n\n    first_login = client.post(\n        "/v1/auth/login",\n        json={"email": email, "password": "strong-password"},\n    )\n    assert first_login.status_code == 200, first_login.text\n\n    def fail_if_called(*_args, **_kwargs):\n        raise AssertionError("evaluation context seeding must not run in repeat auth")\n\n    monkeypatch.setattr("app.api.v1.auth.ensure_evaluation_context", fail_if_called)\n\n    repeat_login = client.post(\n        "/v1/auth/login",\n        json={"email": email, "password": "strong-password"},\n    )\n    assert repeat_login.status_code == 200, repeat_login.text\n    token = repeat_login.json()["access_token"]\n\n    me = client.get(\n        "/v1/auth/me",\n        headers={"Authorization": f"Bearer {token}"},\n    )\n    assert me.status_code == 200, me.text\n    assert me.json()["user"]["email"] == email\n'''
)

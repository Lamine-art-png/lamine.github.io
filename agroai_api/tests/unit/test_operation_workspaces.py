from datetime import datetime

from app.models.saas import Organization, OrganizationMembership, UsageEvent, Workspace


def _register_and_login(client, db, *, email: str, organization: str):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "strong-password",
            "name": "Operation Owner",
            "organization_name": organization,
            "workspace_name": "Initial operation",
            "crop": "Grapes",
            "region": "California",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == body["current_organization"]["id"])
        .first()
    )
    membership.user.email_verification_status = "verified"
    membership.user.email_verified_at = datetime.utcnow()
    db.commit()
    login = client.post("/v1/auth/login", json={"email": email, "password": "strong-password"})
    assert login.status_code == 200, login.text
    return body, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_operation_rename_keeps_workspace_identity_and_records_audit(client, db):
    body, headers = _register_and_login(client, db, email="rename@example.com", organization="Rename Farms")
    workspace_id = client.get("/v1/workspaces", headers=headers).json()["workspaces"][0]["id"]

    response = client.patch(
        f"/v1/workspaces/{workspace_id}",
        headers=headers,
        json={"name": "  Ventura   Avocado Portfolio  "},
    )

    assert response.status_code == 200, response.text
    assert response.json()["workspace"]["id"] == workspace_id
    assert response.json()["workspace"]["name"] == "Ventura Avocado Portfolio"
    assert db.get(Workspace, workspace_id).name == "Ventura Avocado Portfolio"
    audit = (
        db.query(UsageEvent)
        .filter(UsageEvent.workspace_id == workspace_id, UsageEvent.event_type == "workspace_renamed")
        .one()
    )
    assert audit.organization_id == body["current_organization"]["id"]
    assert audit.metadata_json["previous_name"] == "Initial operation"


def test_plan_workspace_limits_are_server_authoritative(client, db):
    body, headers = _register_and_login(client, db, email="limits@example.com", organization="Limit Farms")
    org_id = body["current_organization"]["id"]

    blocked = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"organization_id": org_id, "name": "Second operation", "mode": "evaluation"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "limit_reached"
    assert blocked.json()["detail"]["limit"] == 1

    org = db.get(Organization, org_id)
    org.plan = "professional"
    org.subscription_status = "active"
    db.commit()

    for index in range(2, 6):
        created = client.post(
            "/v1/workspaces",
            headers=headers,
            json={"organization_id": org_id, "name": f"Operation {index}", "mode": "evaluation"},
        )
        assert created.status_code == 201, created.text

    over_limit = client.post(
        "/v1/workspaces",
        headers=headers,
        json={"organization_id": org_id, "name": "Operation 6", "mode": "evaluation"},
    )
    assert over_limit.status_code == 403
    assert over_limit.json()["detail"]["limit"] == 5
    assert db.query(Workspace).filter(Workspace.organization_id == org_id).count() == 5


def test_only_owner_or_admin_can_create_or_rename_operations(client, db):
    owner, owner_headers = _register_and_login(client, db, email="owner-ops@example.com", organization="Owner Operations")
    member, member_headers = _register_and_login(client, db, email="member-ops@example.com", organization="Member Operations")
    owner_org_id = owner["current_organization"]["id"]
    owner_workspace_id = client.get("/v1/workspaces", headers=owner_headers).json()["workspaces"][0]["id"]

    member_user_id = member["user"]["id"]
    db.add(OrganizationMembership(organization_id=owner_org_id, user_id=member_user_id, role="operator"))
    owner_org = db.get(Organization, owner_org_id)
    owner_org.plan = "professional"
    owner_org.subscription_status = "active"
    db.commit()

    create = client.post(
        "/v1/workspaces",
        headers=member_headers,
        json={"organization_id": owner_org_id, "name": "Unauthorized operation", "mode": "evaluation"},
    )
    rename = client.patch(
        f"/v1/workspaces/{owner_workspace_id}",
        headers=member_headers,
        json={"name": "Unauthorized rename"},
    )

    assert create.status_code == 403
    assert create.json()["detail"]["code"] == "owner_or_admin_required"
    assert rename.status_code == 403
    assert rename.json()["detail"]["code"] == "owner_or_admin_required"
    assert db.get(Workspace, owner_workspace_id).name == "Initial operation"

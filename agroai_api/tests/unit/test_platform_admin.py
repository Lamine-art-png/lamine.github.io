from datetime import datetime, timedelta

from app.core.config import settings
from app.core.security import create_access_token
from app.models.saas import Organization, OrganizationMembership, UsageEvent, User, Workspace


def _account(db, *, email: str, name: str, org_name: str, verified: bool = True, plan: str = "free", subscription_status: str = "inactive"):
    user = User(
        email=email,
        name=name,
        password_hash="not-returned",
        email_verification_status="verified" if verified else "unverified",
        email_verified_at=datetime.utcnow() if verified else None,
        is_active=True,
    )
    db.add(user)
    db.flush()
    org = Organization(
        name=org_name,
        slug=org_name.lower().replace(" ", "-"),
        owner_user_id=user.id,
        plan=plan,
        subscription_status=subscription_status,
    )
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(organization_id=org.id, name=f"{org_name} workspace", mode="evaluation")
    db.add_all([membership, workspace])
    db.commit()
    return user, org, workspace


def _headers(user: User, org: Organization):
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": "owner"})
    return {"Authorization": f"Bearer {token}"}


def test_platform_admin_directory_fails_closed_when_allowlist_is_empty(client, db, monkeypatch):
    user, org, _workspace = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    response = client.get("/v1/platform-admin/customers", headers=_headers(user, org))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_admin_required"


def test_organization_owner_cannot_enumerate_platform_customers(client, db, monkeypatch):
    founder, founder_org, _workspace = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    customer, customer_org, _workspace = _account(db, email="customer@example.com", name="Customer", org_name="Customer Org")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", founder.email)
    response = client.get("/v1/platform-admin/customers", headers=_headers(customer, customer_org))
    assert response.status_code == 403
    assert founder.email not in response.text


def test_platform_admin_sees_customer_overview_without_secrets(client, db, monkeypatch):
    founder, founder_org, _workspace = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    customer, customer_org, workspace = _account(
        db,
        email="grower@example.com",
        name="Grower",
        org_name="Grower Farms",
        plan="professional",
        subscription_status="active",
    )
    customer.last_login_at = datetime.utcnow() - timedelta(hours=2)
    db.add(
        UsageEvent(
            organization_id=customer_org.id,
            workspace_id=workspace.id,
            user_id=customer.id,
            event_type="ai_run",
            quantity=3,
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", f"OTHER@example.com, {founder.email.upper()}")

    response = client.get("/v1/platform-admin/customers?sort=newest", headers=_headers(founder, founder_org))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overview"]["total_accounts"] == 2
    assert body["overview"]["verified_accounts"] == 2
    assert body["overview"]["paid_organizations"] == 1
    assert response.headers["cache-control"] == "no-store, private"
    grower = next(row for row in body["customers"] if row["email"] == "grower@example.com")
    assert grower["organizations"][0]["name"] == "Grower Farms"
    assert grower["organizations"][0]["workspace_count"] == 1
    assert grower["activity"]["quantity"] == 3
    serialized = str(body).lower()
    assert "password_hash" not in serialized
    assert "not-returned" not in serialized


def test_platform_admin_filters_and_csv_export_are_protected(client, db, monkeypatch):
    founder, founder_org, _workspace = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    _account(db, email="unverified@example.com", name="Unverified", org_name="Unverified Org", verified=False)
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", founder.email)
    headers = _headers(founder, founder_org)

    filtered = client.get(
        "/v1/platform-admin/customers?verification=unverified&search=Unverified",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["pagination"]["filtered_count"] == 1
    assert filtered.json()["customers"][0]["email"] == "unverified@example.com"

    exported = client.get("/v1/platform-admin/customers.csv", headers=headers)
    assert exported.status_code == 200
    assert "attachment;" in exported.headers["content-disposition"]
    assert "grower" not in exported.text
    assert "founder@example.com" in exported.text
    assert "password" not in exported.text.lower()


def test_auth_me_projects_platform_admin_only_for_allowlisted_verified_user(client, db, monkeypatch):
    founder, founder_org, _workspace = _account(db, email="founder@example.com", name="Founder", org_name="Founder Org")
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", founder.email)
    response = client.get("/v1/auth/me", headers=_headers(founder, founder_org))
    assert response.status_code == 200
    assert response.json()["platform_admin"] is True

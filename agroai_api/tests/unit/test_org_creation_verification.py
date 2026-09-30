"""Creating another organization never bypasses organization screening."""
from tests.unit.test_operations_notifications import _login


def test_additional_organizations_are_not_auto_approved(client, db):
    from app.core.organization_access import organization_access_allowed
    from app.models.saas import Organization

    headers = _login(client, db, "extra-org@example.com")
    response = client.post("/v1/orgs", headers=headers, json={"name": "Unscreened Holdings"})
    assert response.status_code == 201
    org = db.get(Organization, response.json()["organization"]["id"])
    assert org.verification_status == "verification_required"
    assert organization_access_allowed(org) is False

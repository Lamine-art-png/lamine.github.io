"""Owners/admins can remove teammates; members can leave; access ends at once."""
from app.models.saas import OrganizationMembership, SecurityAuditEvent, User
from tests.unit.test_team_invitations import Outbox, _invite, _register  # noqa: F401

import pytest


@pytest.fixture()
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr("app.services.team_invitations.send_email", box)
    return box


def _join(client, db, outbox, owner_headers, email, role):
    assert _invite(client, owner_headers, email=email, role=role).status_code == 200
    accepted = client.post("/v1/team/invitations/accept-new-account", json={
        "token": outbox.last_token(), "name": "QA Member", "password": "Canal-Orchard-Valve-2026",
        "terms_accepted": True, "terms_version": "2026-07-03", "privacy_version": "2026-07-03", "locale": "en",
    })
    assert accepted.status_code == 201, accepted.text
    user = db.query(User).filter_by(email=email).one()
    return {"Authorization": f"Bearer {accepted.json()['access_token']}"}, user


def test_owner_removes_member_and_member_session_stops_working(client, db, outbox):
    owner, org = _register(client, db, "owner-remove@example.com", org_name="Remove Farms")
    member, user = _join(client, db, outbox, owner, "operator-remove@example.com", "operator")
    assert client.get("/v1/team/members", headers=member).status_code == 200
    response = client.delete(f"/v1/team/members/{user.id}", headers=owner)
    assert response.status_code == 200 and response.json()["status"] == "removed"
    assert db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=user.id).first() is None
    assert client.get("/v1/team/members", headers=member).status_code == 401
    assert db.query(SecurityAuditEvent).filter_by(event_type="team.member.removed").count() == 1
    members = client.get("/v1/team/members", headers=owner).json()["members"]
    assert [m["email"] for m in members] == ["owner-remove@example.com"]


def test_member_can_leave_but_cannot_remove_others_or_owner(client, db, outbox):
    owner, org = _register(client, db, "owner-leave@example.com", org_name="Leave Farms")
    operator, operator_user = _join(client, db, outbox, owner, "operator-leave@example.com", "operator")
    viewer, viewer_user = _join(client, db, outbox, owner, "viewer-leave@example.com", "viewer")
    owner_user = db.query(User).filter_by(email="owner-leave@example.com").one()
    assert client.delete(f"/v1/team/members/{viewer_user.id}", headers=operator).status_code == 403
    assert client.delete(f"/v1/team/members/{owner_user.id}", headers=operator).status_code == 409
    assert client.delete(f"/v1/team/members/{owner_user.id}", headers=owner).status_code == 409
    left = client.delete(f"/v1/team/members/{operator_user.id}", headers=operator)
    assert left.status_code == 200 and left.json()["status"] == "left"
    assert db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=operator_user.id).first() is None


def test_admin_cannot_remove_admin_and_other_orgs_are_isolated(client, db, outbox):
    owner, org = _register(client, db, "owner-admin@example.com", org_name="Admin Farms")
    admin, _ = _join(client, db, outbox, owner, "admin-one@example.com", "admin")
    _, admin_two = _join(client, db, outbox, owner, "admin-two@example.com", "admin")
    _, manager = _join(client, db, outbox, owner, "manager-one@example.com", "manager")
    assert client.delete(f"/v1/team/members/{admin_two.id}", headers=admin).status_code == 403
    other_owner, _ = _register(client, db, "owner-other@example.com", org_name="Other Farms")
    assert client.delete(f"/v1/team/members/{manager.id}", headers=other_owner).status_code == 404
    assert client.delete(f"/v1/team/members/{manager.id}", headers=admin).status_code == 200

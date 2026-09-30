"""End-to-end team invitation behaviour: delivery, security, redemption, membership."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models.saas import (
    Organization,
    OrganizationMembership,
    SaaSRequest,
    SelfServiceLegalAcceptance,
    TeamInvitation,
    User,
)
from app.services.team_invitations import hash_invitation_token

PASSWORD = "strong-password"
TERMS = {"terms_accepted": True, "terms_version": "2026-07-03", "privacy_version": "2026-07-03"}


class Outbox:
    def __init__(self):
        self.sent: list[dict] = []
        self.result = {"ok": True, "provider": "resend", "status_code": 200, "reason": "accepted"}

    def __call__(self, **kwargs):
        self.sent.append(kwargs)
        return dict(self.result)

    def last_token(self) -> str:
        match = re.search(r"https://app\.agroai-pilot\.com/accept-invite\?[^\s\"<]+", self.sent[-1]["text_body"])
        assert match, "invitation email must contain the first-party accept link"
        return parse_qs(urlsplit(match.group(0)).query)["token"][0]


@pytest.fixture()
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr("app.services.team_invitations.send_email", box)
    return box


def _register(client, db, email: str, org_name: str = "Shell Farms", plan: str = "team"):
    response = client.post("/v1/auth/register", json={
        "email": email, "password": PASSWORD, "name": f"{email.split('@')[0]} User",
        "organization_name": org_name, "workspace_name": f"{org_name} Workspace", "crop": "Almonds", "region": "California",
    })
    assert response.status_code == 201, response.text
    user = db.query(User).filter(User.email == email).first()
    user.email_verification_status = "verified"
    user.email_verified_at = datetime.utcnow()
    org = db.query(OrganizationMembership).filter(OrganizationMembership.user_id == user.id).first().organization
    org.plan = plan
    org.subscription_status = "active" if plan != "free" else "inactive"
    db.commit()
    login = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, org


def _invite(client, headers, email="teammate@example.com", role="manager", **extra):
    return client.post("/v1/team/invitations", headers=headers, json={"email": email, "role": role, **extra})


def test_invitation_sends_real_email_and_stores_only_token_hash(client, db, outbox):
    headers, org = _register(client, db, "owner-send@example.com", org_name="Sender Farms")
    response = _invite(client, headers, email="  Teammate.One@Example.com ")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "sent" and "sent to teammate.one@example.com" in body["message"]
    assert body["invitation"]["delivery_status"] == "sent"
    assert "token" not in str(body).lower().replace("token_", "")

    assert len(outbox.sent) == 1
    email = outbox.sent[0]
    assert email["to_email"] == "teammate.one@example.com"
    assert "Sender Farms" in email["subject"]
    assert "Manager" in email["text_body"] and "Sender Farms" in email["text_body"]
    assert "contact AGRO-AI" not in email["text_body"]
    token = outbox.last_token()
    assert len(token) >= 40
    assert token in email["html_body"]

    row = db.query(TeamInvitation).filter(TeamInvitation.organization_id == org.id).one()
    assert row.status == "pending" and row.delivery_status == "sent" and row.delivery_attempts == 1
    assert row.token_hash == hash_invitation_token(token) and token not in row.token_hash
    assert timedelta(days=6) < row.expires_at - datetime.utcnow() <= timedelta(days=7)


def test_provider_rejection_is_reported_truthfully_and_link_is_unusable(client, db, outbox):
    headers, org = _register(client, db, "owner-reject@example.com", org_name="Reject Farms")
    outbox.result = {"ok": False, "provider": "resend", "status_code": 422, "reason": "provider_rejected: invalid recipient"}
    response = _invite(client, headers)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "invitation_email_not_delivered"
    assert detail["invitation"]["status"] == "delivery_failed"
    assert "sent" not in detail["message"].split("could not")[0].lower()
    row = db.query(TeamInvitation).filter(TeamInvitation.organization_id == org.id).one()
    assert row.status == "delivery_failed" and row.token_hash is None
    assert row.delivery_error.startswith("provider_rejected")
    gap = db.query(SaaSRequest).filter(SaaSRequest.organization_id == org.id).all()
    assert any((r.metadata_json or {}).get("request_type") == "team_invitation_delivery" for r in gap)
    preview = client.post("/v1/team/invitations/preview", json={"token": outbox.last_token()})
    assert preview.status_code == 404


def test_unconfigured_provider_never_claims_sent(client, db, outbox):
    headers, _org = _register(client, db, "owner-noprov@example.com", org_name="NoProvider Farms")
    outbox.result = {"ok": False, "provider": "none", "reason": "email_provider_not_configured"}
    response = _invite(client, headers)
    assert response.status_code == 502
    assert response.json()["detail"]["invitation"]["delivery_status"] == "not_configured"


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "x@@example.com", "person@example"])
def test_invalid_recipient_rejected_without_email(client, db, outbox, email):
    headers, _org = _register(client, db, f"owner-invalid-{abs(hash(email))}@example.com", org_name="Invalid Farms")
    response = _invite(client, headers, email=email)
    assert response.status_code == 422
    assert outbox.sent == []


def test_duplicate_open_invitation_rejected_and_resend_rotates_single_valid_link(client, db, outbox):
    headers, org = _register(client, db, "owner-dup@example.com", org_name="Dup Farms")
    assert _invite(client, headers).status_code == 200
    first = outbox.last_token()
    dup = _invite(client, headers)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "invitation_pending"
    row = db.query(TeamInvitation).filter(TeamInvitation.organization_id == org.id).one()
    row.last_sent_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()
    resend = client.post(f"/v1/team/invitations/{row.id}/resend", headers=headers)
    assert resend.status_code == 200 and resend.json()["status"] == "sent"
    second = outbox.last_token()
    assert second != first
    assert client.post("/v1/team/invitations/preview", json={"token": first}).status_code == 404
    assert client.post("/v1/team/invitations/preview", json={"token": second}).status_code == 200
    too_soon = client.post(f"/v1/team/invitations/{row.id}/resend", headers=headers)
    assert too_soon.status_code == 429


def test_role_enforcement(client, db, outbox):
    headers, org = _register(client, db, "owner-roles@example.com", org_name="Role Farms")
    owner_invite = _invite(client, headers, email="new-owner@example.com", role="owner")
    assert owner_invite.status_code == 403 and owner_invite.json()["detail"]["code"] == "role_not_assignable"
    # An admin may not create another admin.
    admin = User(email="admin-roles@example.com", name="Admin", password_hash=None, email_verification_status="verified", email_verified_at=datetime.utcnow())
    db.add(admin)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=admin.id, role="admin", status="active"))
    db.commit()
    from app.core.security import create_access_token
    admin_headers = {"Authorization": "Bearer " + create_access_token({"sub": admin.id, "tenant_id": org.id, "org_id": org.id, "role": "admin"})}
    assert _invite(client, admin_headers, email="peer-admin@example.com", role="admin").status_code == 403
    assert _invite(client, admin_headers, email="op@example.com", role="operator").status_code == 200
    # Operators cannot invite at all.
    viewer = User(email="op-roles@example.com", name="Op", email_verification_status="verified", email_verified_at=datetime.utcnow())
    db.add(viewer)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=viewer.id, role="operator", status="active"))
    db.commit()
    op_headers = {"Authorization": "Bearer " + create_access_token({"sub": viewer.id, "tenant_id": org.id, "org_id": org.id, "role": "operator"})}
    assert _invite(client, op_headers, email="x@example.com", role="viewer").status_code == 403


def test_plan_entitlement_enforced(client, db, outbox):
    headers, _org = _register(client, db, "owner-free@example.com", org_name="Free Farms", plan="free")
    response = _invite(client, headers)
    assert response.status_code == 402
    assert outbox.sent == []


def test_new_account_acceptance_creates_verified_member_with_role_and_legal_record(client, db, outbox):
    headers, org = _register(client, db, "owner-newacct@example.com", org_name="Newacct Farms")
    assert _invite(client, headers, email="fresh@example.com", role="operator", locale="pt-BR").status_code == 200
    token = outbox.last_token()
    preview = client.post("/v1/team/invitations/preview", json={"token": token})
    assert preview.status_code == 200
    expected = {"organization_name": "Newacct Farms", "role": "operator", "email": "fresh@example.com", "account_exists": False}
    assert {key: preview.json()[key] for key in expected} == expected

    missing_terms = client.post("/v1/team/invitations/accept-new-account", json={"token": token, "name": "Fresh", "password": PASSWORD})
    assert missing_terms.status_code == 422

    accepted = client.post("/v1/team/invitations/accept-new-account", json={"token": token, "name": "Fresh Person", "password": PASSWORD, **TERMS})
    assert accepted.status_code == 201, accepted.text
    session = accepted.json()
    assert session["current_organization"]["id"] == org.id and session["current_organization"]["role"] == "operator"
    user = db.query(User).filter(User.email == "fresh@example.com").one()
    assert user.email_verification_status == "verified" and user.password_hash != PASSWORD
    membership = db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=user.id).one()
    assert membership.role == "operator" and membership.status == "active"
    legal = db.query(SelfServiceLegalAcceptance).filter_by(user_id=user.id).one()
    assert legal.organization_id == org.id and legal.authority_confirmed is False and legal.locale == "pt-BR"
    row = db.query(TeamInvitation).filter_by(organization_id=org.id).one()
    assert row.status == "accepted" and row.token_hash is None and row.accepted_by_user_id == user.id

    # Replay of the same link is rejected, and the new member can sign in and sees the team.
    assert client.post("/v1/team/invitations/accept-new-account", json={"token": token, "name": "Again", "password": PASSWORD, **TERMS}).status_code == 404
    login = client.post("/v1/auth/login", json={"email": "fresh@example.com", "password": PASSWORD})
    assert login.status_code == 200
    members = client.get("/v1/team/members", headers={"Authorization": f"Bearer {session['access_token']}"})
    assert "fresh@example.com" in {m["email"] for m in members.json()["members"]}
    owner_view = client.get("/v1/team/invitations", headers=headers).json()["invitations"][0]
    assert owner_view["status"] == "accepted" and owner_view["accepted_at"]


def test_existing_account_acceptance_and_second_redemption_rejected(client, db, outbox):
    headers, org = _register(client, db, "owner-existing@example.com", org_name="Existing Farms")
    invitee_headers, invitee_org = _register(client, db, "invitee-existing@example.com", org_name="Invitee Own Farms", plan="free")
    assert _invite(client, headers, email="invitee-existing@example.com", role="viewer").status_code == 200
    token = outbox.last_token()
    assert client.post("/v1/team/invitations/preview", json={"token": token}).json()["account_exists"] is True
    accepted = client.post("/v1/team/invitations/accept", headers=invitee_headers, json={"token": token})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["current_organization"]["id"] == org.id
    user = db.query(User).filter(User.email == "invitee-existing@example.com").one()
    roles = {m.organization_id: m.role for m in db.query(OrganizationMembership).filter_by(user_id=user.id)}
    assert roles == {invitee_org.id: "owner", org.id: "viewer"}
    again = client.post("/v1/team/invitations/accept", headers=invitee_headers, json={"token": token})
    assert again.status_code == 404


def test_wrong_account_cannot_redeem(client, db, outbox):
    headers, org = _register(client, db, "owner-wrong@example.com", org_name="Wrong Farms")
    other_headers, _ = _register(client, db, "intruder@example.com", org_name="Intruder Farms", plan="free")
    assert _invite(client, headers, email="rightful@example.com").status_code == 200
    token = outbox.last_token()
    response = client.post("/v1/team/invitations/accept", headers=other_headers, json={"token": token})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "invitation_email_mismatch"
    intruder = db.query(User).filter(User.email == "intruder@example.com").one()
    assert not db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=intruder.id).first()
    assert db.query(TeamInvitation).filter_by(organization_id=org.id).one().status == "pending"


def test_cross_tenant_management_rejected(client, db, outbox):
    headers_a, org_a = _register(client, db, "owner-tenant-a@example.com", org_name="Tenant A")
    headers_b, _org_b = _register(client, db, "owner-tenant-b@example.com", org_name="Tenant B")
    assert _invite(client, headers_a, email="a-member@example.com").status_code == 200
    row = db.query(TeamInvitation).filter_by(organization_id=org_a.id).one()
    assert client.delete(f"/v1/team/invitations/{row.id}", headers=headers_b).status_code == 404
    assert client.post(f"/v1/team/invitations/{row.id}/resend", headers=headers_b).status_code == 404
    assert all(i["id"] != row.id for i in client.get("/v1/team/invitations", headers=headers_b).json()["invitations"])
    db.refresh(row)
    assert row.status == "pending"


def test_revoked_and_expired_invitations_cannot_be_redeemed(client, db, outbox):
    headers, org = _register(client, db, "owner-revoke@example.com", org_name="Revoke Farms")
    assert _invite(client, headers, email="revoked@example.com").status_code == 200
    revoked_token = outbox.last_token()
    row = db.query(TeamInvitation).filter_by(organization_id=org.id, email="revoked@example.com").one()
    assert client.delete(f"/v1/team/invitations/{row.id}", headers=headers).json()["invitation"]["status"] == "revoked"
    assert client.post("/v1/team/invitations/preview", json={"token": revoked_token}).status_code == 404

    assert _invite(client, headers, email="late@example.com").status_code == 200
    late_token = outbox.last_token()
    late = db.query(TeamInvitation).filter_by(organization_id=org.id, email="late@example.com").one()
    late.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get("/v1/team/invitations", headers=headers).json()["invitations"][0]["status"] == "expired"
    response = client.post("/v1/team/invitations/accept-new-account", json={"token": late_token, "name": "Late", "password": PASSWORD, **TERMS})
    assert response.status_code == 410 and response.json()["detail"]["code"] == "invitation_expired"
    db.refresh(late)
    assert late.status == "expired" and late.token_hash is None
    assert not db.query(User).filter(User.email == "late@example.com").first()


def test_already_member_rejected(client, db, outbox):
    headers, _org = _register(client, db, "owner-member@example.com", org_name="Member Farms")
    response = _invite(client, headers, email="owner-member@example.com")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "already_member"


def test_seat_limit_enforced(client, db, outbox, monkeypatch):
    headers, _org = _register(client, db, "owner-seats@example.com", org_name="Seat Farms")
    monkeypatch.setattr("app.services.team_invitations._seat_limit", lambda _db, _org: 2)
    assert _invite(client, headers, email="seat1@example.com").status_code == 200
    blocked = _invite(client, headers, email="seat2@example.com")
    assert blocked.status_code == 402 and blocked.json()["detail"]["code"] == "seat_limit_reached"


def test_invitation_email_is_localized_with_intact_link(client, db, outbox):
    headers, _org = _register(client, db, "owner-locale@example.com", org_name="Locale Farms")
    assert _invite(client, headers, email="pt@example.com", locale="pt-BR").status_code == 200
    email = outbox.sent[-1]
    assert "Accept invitation" not in email["html_body"]
    assert 'lang="pt-BR"' in email["html_body"]
    assert "Locale Farms" in email["subject"]
    token = outbox.last_token()
    assert f"lang=pt-BR" in email["text_body"] and token in email["text_body"]


def test_unverified_existing_account_cannot_redeem(client, db, outbox):
    headers, org = _register(client, db, "owner-unverified@example.com")
    invitee_headers, _ = _register(client, db, "unverified-invitee@example.com")
    user = db.query(User).filter_by(email="unverified-invitee@example.com").one()
    user.email_verification_status, user.email_verified_at = "pending", None
    db.commit()
    assert _invite(client, headers, email=user.email).status_code == 200
    response = client.post("/v1/team/invitations/accept", headers=invitee_headers, json={"token": outbox.last_token()})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "email_verification_required"
    assert not db.query(OrganizationMembership).filter_by(organization_id=org.id, user_id=user.id).first()


def test_revocation_during_provider_call_cannot_be_undone(client, db, monkeypatch):
    headers, org = _register(client, db, "owner-race@example.com")
    def revoke_while_sending(**kwargs):
        row = db.query(TeamInvitation).filter_by(organization_id=org.id).one()
        row.status, row.token_hash = "revoked", None
        db.commit()
        return {"ok": True, "provider": "resend"}
    monkeypatch.setattr("app.services.team_invitations.send_email", revoke_while_sending)
    response = _invite(client, headers)
    assert response.status_code == 502
    row = db.query(TeamInvitation).filter_by(organization_id=org.id).one()
    assert row.status == "revoked" and row.token_hash is None


def test_sending_link_cannot_be_redeemed_and_duplicate_resend_is_blocked(client, db, outbox):
    headers, org = _register(client, db, "owner-sending@example.com")
    assert _invite(client, headers).status_code == 200
    token = outbox.last_token()
    row = db.query(TeamInvitation).filter_by(organization_id=org.id).one()
    row.delivery_status, row.last_sent_at = "sending", None
    db.commit()
    assert client.post("/v1/team/invitations/preview", json={"token": token}).status_code == 404
    assert client.post(f"/v1/team/invitations/{row.id}/resend", headers=headers).status_code == 429
    assert len(outbox.sent) == 1


def test_expired_invitation_resend_cannot_duplicate_new_invitation(client, db, outbox):
    headers, org = _register(client, db, "owner-expired-resend@example.com")
    assert _invite(client, headers).status_code == 200
    old = db.query(TeamInvitation).filter_by(organization_id=org.id).one()
    old.expires_at = datetime.utcnow() - timedelta(days=1)
    old.last_sent_at = datetime.utcnow() - timedelta(days=8)
    db.commit()
    assert _invite(client, headers).status_code == 200
    assert client.post(f"/v1/team/invitations/{old.id}/resend", headers=headers).status_code == 409
    assert len(outbox.sent) == 2

from __future__ import annotations

from datetime import datetime

from app.api.deps import _activate_server_authorized_access_profile
from app.core.config import settings
from app.models.saas import EntitlementOverride, Organization, OrganizationMembership, User, Workspace
from app.services.non_customer_access import access_profile_metadata, activate_configured_profile


def _verified_user(db, *, email: str, name: str) -> User:
    user = User(
        email=email,
        name=name,
        password_hash="not-used",
        is_active=True,
        email_verified_at=datetime.utcnow(),
        email_verification_status="verified",
    )
    db.add(user)
    db.flush()
    return user


def test_allowlisted_member_cannot_self_activate_foreign_organization(db, monkeypatch):
    owner = _verified_user(db, email="owner@example.test", name="Owner")
    allowlisted_member = _verified_user(db, email="internal-member@example.test", name="Internal Member")
    org = Organization(
        name="Customer Owned Org",
        slug="customer-owned-org",
        owner_user_id=owner.id,
        plan="free",
        subscription_status="inactive",
        subscription_source="local",
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
    db.add(OrganizationMembership(organization_id=org.id, user_id=allowlisted_member.id, role="admin"))
    db.add(Workspace(organization_id=org.id, name="Customer Workspace", mode="evaluation"))
    db.commit()

    monkeypatch.setattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "internal-member@example.test")

    assert activate_configured_profile(db, user=allowlisted_member, org=org) is None
    _activate_server_authorized_access_profile(db, allowlisted_member, org)

    db.refresh(org)
    assert org.plan == "free"
    assert org.subscription_status == "inactive"
    assert org.subscription_source == "local"
    assert access_profile_metadata(org)["profile"] == "customer"
    assert (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == org.id)
        .count()
        == 0
    )


def test_allowlisted_owner_can_self_activate_owned_organization(db, monkeypatch):
    owner = _verified_user(db, email="internal-owner@example.test", name="Internal Owner")
    org = Organization(
        name="Internal Owned Org",
        slug="internal-owned-org",
        owner_user_id=owner.id,
        plan="free",
        subscription_status="inactive",
        subscription_source="local",
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
    db.add(Workspace(organization_id=org.id, name="Internal Workspace", mode="evaluation"))
    db.commit()

    monkeypatch.setattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "internal-owner@example.test")

    _activate_server_authorized_access_profile(db, owner, org)

    db.refresh(org)
    assert org.plan == "enterprise"
    assert org.subscription_status == "contracted"
    assert org.subscription_source == "access_profile:internal"
    assert access_profile_metadata(org)["profile"] == "internal"

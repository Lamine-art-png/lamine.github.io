from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.api.v1.billing import _activate_authorized_non_customer_before_billing, _billing_not_required
from app.core.config import settings
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services.non_customer_access import access_profile_metadata


def _identity(db, *, email: str, verified: bool = True):
    user = User(
        email=email,
        name="Founder",
        password_hash="not-used",
        is_active=True,
        email_verified_at=datetime.utcnow() if verified else None,
        email_verification_status="verified" if verified else "unverified",
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Founder Billing Preflight",
        slug=f"billing-preflight-{user.id}",
        owner_user_id=user.id,
        plan="free",
        subscription_status="inactive",
        subscription_source="local",
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(Workspace(organization_id=org.id, name="Evaluation", mode="evaluation"))
    db.commit()
    return user, org


def test_verified_allowlisted_founder_is_activated_before_checkout_can_run(db, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "founder-billing@example.test")
    user, org = _identity(db, email="founder-billing@example.test", verified=True)

    assert access_profile_metadata(org)["profile"] == "customer"
    _activate_authorized_non_customer_before_billing(db, user, org)

    assert access_profile_metadata(org)["profile"] == "internal"
    assert org.plan == "enterprise"
    assert org.subscription_status == "contracted"
    guard = _billing_not_required(org)
    assert isinstance(guard, HTTPException)
    assert guard.status_code == 409
    assert guard.detail["code"] == "billing_not_required"


def test_unverified_allowlisted_identity_is_not_granted_internal_access(db, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "unverified@example.test")
    user, org = _identity(db, email="unverified@example.test", verified=False)

    _activate_authorized_non_customer_before_billing(db, user, org)

    assert access_profile_metadata(org)["profile"] == "customer"
    assert org.plan == "free"
    assert _billing_not_required(org) is None

from __future__ import annotations

from datetime import datetime

import app.services.non_customer_access as access_service
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services.non_customer_access import DEMO_PROFILE, INTERNAL_PROFILE, provision_non_customer_access


def _owned_identity(db, *, email: str):
    user = User(
        email=email,
        name="Owner",
        password_hash="not-used",
        is_active=True,
        email_verified_at=datetime.utcnow(),
        email_verification_status="verified",
    )
    db.add(user)
    db.flush()
    org = Organization(
        name=f"Org {user.id}",
        slug=f"org-{user.id}",
        owner_user_id=user.id,
        plan="free",
        subscription_status="inactive",
        subscription_source="local",
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(Workspace(organization_id=org.id, name="Workspace", mode="evaluation"))
    db.commit()
    return user, org


def test_internal_profile_does_not_inject_evaluation_context(db, monkeypatch):
    user, org = _owned_identity(db, email="internal-data-isolation@example.test")
    calls = []
    monkeypatch.setattr(access_service, "ensure_evaluation_context", lambda *args, **kwargs: calls.append((args, kwargs)))

    provision_non_customer_access(db, user=user, org=org, profile=INTERNAL_PROFILE)

    assert calls == []


def test_demo_profile_may_seed_labelled_evaluation_context(db, monkeypatch):
    user, org = _owned_identity(db, email="demo-data-isolation@example.test")
    calls = []
    monkeypatch.setattr(access_service, "ensure_evaluation_context", lambda *args, **kwargs: calls.append((args, kwargs)))

    provision_non_customer_access(db, user=user, org=org, profile=DEMO_PROFILE)

    assert len(calls) == 1
    assert calls[0][0][1].id == org.id

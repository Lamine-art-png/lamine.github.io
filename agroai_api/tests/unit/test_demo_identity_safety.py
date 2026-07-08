from __future__ import annotations

from datetime import datetime

import pytest

from app.core.config import settings
from app.models.saas import Organization, OrganizationMembership, User
from app.services.demo_environment import provision_demo_environment


def test_demo_seed_refuses_existing_non_demo_customer_identity_without_mutation(db, monkeypatch):
    original_hash = "customer-password-hash-must-survive"
    user = User(
        email="real-customer@example.test",
        name="Real Customer",
        password_hash=original_hash,
        is_active=True,
        email_verified_at=datetime.utcnow(),
        email_verification_status="verified",
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Real Customer Org",
        slug="real-customer-org",
        owner_user_id=user.id,
        plan="professional",
        subscription_status="active",
        subscription_source="stripe",
        commercial_metadata_json={"customer_record": True},
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.commit()

    monkeypatch.setattr(settings, "DEMO_FULL_EMAIL", "real-customer@example.test")
    monkeypatch.setattr(settings, "DEMO_FULL_PASSWORD", "new-demo-password-123")
    monkeypatch.setattr(settings, "DEMO_FREE_EMAIL", "free-demo-safe@example.test")
    monkeypatch.setattr(settings, "DEMO_FREE_PASSWORD", "free-demo-password-123")

    with pytest.raises(ValueError, match="Refusing to repurpose pre-existing non-demo identity"):
        provision_demo_environment(db)

    db.refresh(user)
    db.refresh(org)
    assert user.password_hash == original_hash
    assert user.name == "Real Customer"
    assert org.plan == "professional"
    assert org.subscription_status == "active"
    assert org.subscription_source == "stripe"
    assert org.commercial_metadata_json == {"customer_record": True}

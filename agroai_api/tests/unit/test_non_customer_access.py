from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api.v1.billing import _billing_not_required
from app.api.v1.non_customer_access import _demo_autoprovision_enabled
from app.core.config import settings
from app.models.saas import EntitlementOverride, ManagedEntity, Organization, OrganizationMembership, User, Workspace
from app.services.commercial_billing_lifecycle import apply_authoritative_billing_event
from app.services.commercial_control import resolve_effective_entitlements
from app.services.demo_environment import provision_demo_environment
from app.services.entitlements import serialize_entitlements
from app.services.non_customer_access import (
    DEMO_PROFILE,
    INTERNAL_PROFILE,
    access_profile_metadata,
    configured_profile_for_email,
    full_access_overrides,
    provision_non_customer_access,
    revoke_non_customer_access,
)


def _identity(db, *, email: str = "founder@example.test") -> tuple[User, Organization]:
    user = User(
        email=email,
        name="Founder",
        password_hash="not-used-in-unit-test",
        is_active=True,
        email_verified_at=datetime.utcnow(),
        email_verification_status="verified",
    )
    db.add(user)
    db.flush()
    org = Organization(
        name="Founder Org",
        slug=f"founder-{user.id}",
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


def test_profile_selection_is_server_allowlist_only(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "founder@example.test, ceo@example.test")
    monkeypatch.setattr(settings, "DEMO_FULL_ACCESS_EMAILS", "demo@example.test")

    assert configured_profile_for_email(" FOUNDER@example.test ") == INTERNAL_PROFILE
    assert configured_profile_for_email("demo@example.test") == DEMO_PROFILE
    assert configured_profile_for_email("customer@example.test") == "customer"


def test_demo_autoprovision_requires_demo_environment_and_explicit_flag(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEMO_AUTO_PROVISION", True)
    assert _demo_autoprovision_enabled() is False

    monkeypatch.setattr(settings, "APP_ENV", "demo")
    monkeypatch.setattr(settings, "DEMO_AUTO_PROVISION", False)
    assert _demo_autoprovision_enabled() is False

    monkeypatch.setattr(settings, "DEMO_AUTO_PROVISION", True)
    assert _demo_autoprovision_enabled() is True


def test_internal_access_is_full_unmetered_idempotent_and_reversible(db):
    user, org = _identity(db)

    result = provision_non_customer_access(db, user=user, org=org, profile=INTERNAL_PROFILE)
    db.commit()
    assert result.profile == INTERNAL_PROFILE
    assert org.plan == "enterprise"
    assert org.subscription_status == "contracted"
    assert org.subscription_source == "access_profile:internal"
    assert access_profile_metadata(org) == {
        "profile": "internal",
        "billing_required": False,
        "demo_data_policy": "internal_authorized_use",
    }

    effective = resolve_effective_entitlements(db, org)
    assert effective.state("reports.pdf_export") == "enabled"
    assert effective.state("connectors.custom_integration") == "enabled"
    assert effective.state("governance.custom_retention") == "enabled"
    assert effective.value("quota.ai_action.monthly") is None
    assert effective.value("quota.deep_investigation.monthly") is None

    expected_override_count = len(full_access_overrides())
    count_after_first = (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == org.id)
        .count()
    )
    assert count_after_first == expected_override_count

    second = provision_non_customer_access(db, user=user, org=org, profile=INTERNAL_PROFILE)
    db.commit()
    count_after_second = (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == org.id)
        .count()
    )
    assert second.override_count == expected_override_count
    assert count_after_second == count_after_first

    assert revoke_non_customer_access(db, org=org) is True
    db.commit()
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


def test_legacy_entitlement_serialization_matches_full_access_profile(db):
    user, org = _identity(db)
    provision_non_customer_access(db, user=user, org=org, profile=DEMO_PROFILE)
    db.commit()

    payload = serialize_entitlements(org)
    assert payload["access_profile"] == "demo"
    assert payload["billing_required"] is False
    assert payload["capabilities"]["connectors.custom_integration"] == "enabled"
    assert payload["capabilities"]["governance.custom_retention"] == "enabled"
    assert payload["quotas"]["ai_action.monthly"] is None


def test_non_customer_profile_cannot_enter_stripe_checkout_and_ignores_webhook_mutation(db):
    user, org = _identity(db)
    provision_non_customer_access(db, user=user, org=org, profile=INTERNAL_PROFILE)
    db.commit()

    guard = _billing_not_required(org)
    assert isinstance(guard, HTTPException)
    assert guard.status_code == 409
    assert guard.detail["code"] == "billing_not_required"

    apply_authoritative_billing_event(
        db,
        org,
        "customer.subscription.deleted",
        {"id": "sub_stale", "customer": "cus_stale"},
    )
    assert org.plan == "enterprise"
    assert org.subscription_status == "contracted"
    assert org.subscription_source == "access_profile:internal"


def test_normal_customer_still_obeys_authoritative_stripe_lifecycle(db):
    _user, org = _identity(db, email="customer@example.test")
    org.plan = "professional"
    org.subscription_status = "active"
    org.subscription_source = "stripe"
    org.stripe_customer_id = "cus_customer"
    org.stripe_subscription_id = "sub_customer"
    db.commit()

    assert _billing_not_required(org) is None
    apply_authoritative_billing_event(
        db,
        org,
        "customer.subscription.deleted",
        {"id": "sub_customer", "customer": "cus_customer"},
    )
    assert org.plan == "free"
    assert org.subscription_status == "canceled"
    assert org.subscription_source == "stripe"


def test_demo_environment_provisions_full_and_real_free_identities_idempotently(db, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_FULL_EMAIL", "full-demo@example.test")
    monkeypatch.setattr(settings, "DEMO_FULL_PASSWORD", "full-demo-password-123")
    monkeypatch.setattr(settings, "DEMO_FREE_EMAIL", "free-demo@example.test")
    monkeypatch.setattr(settings, "DEMO_FREE_PASSWORD", "free-demo-password-123")
    monkeypatch.setattr(settings, "DEMO_FULL_ORGANIZATION_NAME", "AGRO-AI Demo Organization")
    monkeypatch.setattr(settings, "DEMO_FREE_ORGANIZATION_NAME", "AGRO-AI Free Demo")

    first = provision_demo_environment(db)
    assert {item.access_profile for item in first} == {"demo", "customer"}

    full_user = db.query(User).filter(User.email == "full-demo@example.test").one()
    free_user = db.query(User).filter(User.email == "free-demo@example.test").one()
    full_org = full_user.memberships[0].organization
    free_org = free_user.memberships[0].organization

    assert full_org.plan == "enterprise"
    assert full_org.subscription_status == "contracted"
    assert access_profile_metadata(full_org)["profile"] == "demo"
    assert free_org.plan == "free"
    assert free_org.subscription_status == "inactive"
    assert access_profile_metadata(free_org)["profile"] == "customer"

    full_workspace_names = {
        row.name
        for row in db.query(Workspace).filter(Workspace.organization_id == full_org.id).all()
    }
    assert {
        "Ventura County Avocado Operations",
        "Coquimbo Table Grapes",
        "Central Valley Almond Operations",
    }.issubset(full_workspace_names)

    demo_entities = (
        db.query(ManagedEntity)
        .filter(ManagedEntity.organization_id == full_org.id)
        .all()
    )
    assert len(demo_entities) == 3
    assert all(row.metadata_json["customer_data_claim"] is False for row in demo_entities)
    assert all(row.metadata_json["operational_use"] is False for row in demo_entities)
    assert all(row.metadata_json["data_class"] == "simulated_or_evaluation" for row in demo_entities)

    second = provision_demo_environment(db)
    assert len(second) == 2
    assert db.query(User).filter(User.email.in_(["full-demo@example.test", "free-demo@example.test"])).count() == 2
    assert db.query(ManagedEntity).filter(ManagedEntity.organization_id == full_org.id).count() == 3


def test_demo_seed_rejects_shared_identity(db, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_FULL_EMAIL", "same@example.test")
    monkeypatch.setattr(settings, "DEMO_FULL_PASSWORD", "full-demo-password-123")
    monkeypatch.setattr(settings, "DEMO_FREE_EMAIL", "same@example.test")
    monkeypatch.setattr(settings, "DEMO_FREE_PASSWORD", "free-demo-password-123")

    with pytest.raises(ValueError, match="different emails"):
        provision_demo_environment(db)

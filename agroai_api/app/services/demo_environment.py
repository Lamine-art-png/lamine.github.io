"""Idempotent AGRO-AI demo-environment identity and portfolio seed.

The full demo identity is provisioned through the canonical entitlement override
plane. The free demo identity deliberately remains a genuine Free customer state
so launch recordings can show the real commercial boundaries.

All seeded operational context is marked as evaluation/demo material. This module
never claims that a live connector or customer telemetry stream is connected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import pwd_context
from app.models.saas import ManagedEntity, Organization, OrganizationMembership, User, Workspace
from app.services.evaluation_seed import ensure_evaluation_context
from app.services.non_customer_access import DEMO_PROFILE, provision_non_customer_access

DEMO_SEED_SOURCE = "demo_environment"


@dataclass(frozen=True)
class DemoIdentityResult:
    email: str
    organization_id: str
    organization_slug: str
    access_profile: str
    created_user: bool
    created_organization: bool


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _slug_base(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "agro-ai-demo"


def _unique_slug(db: Session, value: str) -> str:
    base = _slug_base(value)
    candidate = base
    suffix = 2
    while db.query(Organization).filter(Organization.slug == candidate).first():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _assert_existing_identity_is_demo_owned(db: Session, user: User) -> None:
    """Refuse to reset/reuse any identity not already owned by this demo seed.

    A typo or bad environment variable must never convert a real customer/founder
    account into a demo identity or rotate its password.
    """

    memberships = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user.id)
        .all()
    )
    if not memberships:
        raise ValueError(
            f"Refusing to repurpose pre-existing non-demo identity: {user.email}"
        )
    for membership in memberships:
        metadata = (
            membership.organization.commercial_metadata_json
            if isinstance(membership.organization.commercial_metadata_json, dict)
            else {}
        )
        if metadata.get("seed_source") != DEMO_SEED_SOURCE:
            raise ValueError(
                f"Refusing to repurpose pre-existing non-demo identity: {user.email}"
            )


def _get_or_create_user(db: Session, *, email: str, password: str, name: str) -> tuple[User, bool]:
    normalized = _normalize_email(email)
    if not normalized or "@" not in normalized:
        raise ValueError("A valid demo identity email is required")
    if len(password or "") < 12:
        raise ValueError("Demo identity passwords must contain at least 12 characters")

    user = db.query(User).filter(User.email == normalized).first()
    created = user is None
    if user is None:
        user = User(
            email=normalized,
            name=name,
            password_hash=pwd_context.hash(password),
            is_active=True,
            email_verified_at=datetime.utcnow(),
            email_verification_status="verified",
        )
        db.add(user)
        db.flush()
    else:
        _assert_existing_identity_is_demo_owned(db, user)
        # Only identities already proven to belong to the demo seed converge on
        # environment-owned credentials during idempotent reprovisioning.
        user.name = user.name or name
        user.password_hash = pwd_context.hash(password)
        user.is_active = True
        user.email_verified_at = user.email_verified_at or datetime.utcnow()
        user.email_verification_status = "verified"
    return user, created


def _first_membership(db: Session, user_id: str) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user_id)
        .order_by(OrganizationMembership.created_at.asc())
        .first()
    )


def _get_or_create_org(
    db: Session,
    *,
    user: User,
    name: str,
    profile: str,
) -> tuple[Organization, OrganizationMembership, bool]:
    membership = _first_membership(db, user.id)
    if membership is not None:
        return membership.organization, membership, False

    org = Organization(
        name=name,
        slug=_unique_slug(db, name),
        owner_user_id=user.id,
        plan="free",
        subscription_status="inactive",
        subscription_source="demo_seed",
        commercial_metadata_json={
            "seed_source": DEMO_SEED_SOURCE,
            "operational_use": False,
            "requested_access_profile": profile,
        },
    )
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    db.flush()
    return org, membership, True


def _workspace_specs() -> list[tuple[str, str, str]]:
    return [
        ("Ventura County Avocado Operations", "avocado", "Ventura County, California"),
        ("Coquimbo Table Grapes", "table grapes", "Coquimbo Region, Chile"),
        ("Central Valley Almond Operations", "almonds", "Central Valley, California"),
    ]


def _ensure_full_demo_portfolio(db: Session, org: Organization) -> None:
    workspaces: list[Workspace] = []
    for name, crop, region in _workspace_specs():
        workspace = (
            db.query(Workspace)
            .filter(Workspace.organization_id == org.id, Workspace.name == name)
            .first()
        )
        if workspace is None:
            workspace = Workspace(
                organization_id=org.id,
                name=name,
                crop=crop,
                region=region,
                mode="evaluation",
            )
            db.add(workspace)
            db.flush()
        else:
            workspace.crop = crop
            workspace.region = region
            workspace.mode = "evaluation"
        workspaces.append(workspace)

    # Seed the existing truthful evaluation context against the first workspace.
    ensure_evaluation_context(db, org, workspaces[0] if workspaces else None)

    entity_specs = [
        ("farm", "demo-ventura-avocado", "Ventura Avocado Portfolio", workspaces[0] if workspaces else None),
        ("farm", "demo-coquimbo-grapes", "Coquimbo Table Grape Portfolio", workspaces[1] if len(workspaces) > 1 else None),
        ("farm", "demo-central-valley-almonds", "Central Valley Almond Portfolio", workspaces[2] if len(workspaces) > 2 else None),
    ]
    for entity_type, external_id, display_name, workspace in entity_specs:
        row = (
            db.query(ManagedEntity)
            .filter(
                ManagedEntity.organization_id == org.id,
                ManagedEntity.entity_type == entity_type,
                ManagedEntity.external_id == external_id,
            )
            .first()
        )
        metadata = {
            "source": "demo_seed",
            "data_class": "simulated_or_evaluation",
            "operational_use": False,
            "customer_data_claim": False,
            "label": "Demo",
        }
        if row is None:
            row = ManagedEntity(
                organization_id=org.id,
                workspace_id=workspace.id if workspace else None,
                entity_type=entity_type,
                external_id=external_id,
                display_name=display_name,
                status="active",
                metadata_json=metadata,
            )
            db.add(row)
        else:
            row.workspace_id = workspace.id if workspace else row.workspace_id
            row.display_name = display_name
            row.status = "active"
            row.metadata_json = metadata


def _ensure_free_demo_workspace(db: Session, org: Organization) -> None:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.organization_id == org.id)
        .order_by(Workspace.created_at.asc())
        .first()
    )
    if workspace is None:
        workspace = Workspace(
            organization_id=org.id,
            name="Free Demo Workspace",
            crop="mixed crops",
            region="Evaluation",
            mode="evaluation",
        )
        db.add(workspace)
        db.flush()
    ensure_evaluation_context(db, org, workspace)


def provision_demo_environment(db: Session) -> list[DemoIdentityResult]:
    """Create/update the configured full and free demo identities atomically."""

    full_email = _normalize_email(getattr(settings, "DEMO_FULL_EMAIL", ""))
    free_email = _normalize_email(getattr(settings, "DEMO_FREE_EMAIL", ""))
    full_password = str(getattr(settings, "DEMO_FULL_PASSWORD", "") or "")
    free_password = str(getattr(settings, "DEMO_FREE_PASSWORD", "") or "")

    if not full_email or not free_email:
        raise ValueError("DEMO_FULL_EMAIL and DEMO_FREE_EMAIL must both be configured")
    if full_email == free_email:
        raise ValueError("Full-access and Free demo identities must use different emails")

    results: list[DemoIdentityResult] = []

    full_user, full_user_created = _get_or_create_user(
        db,
        email=full_email,
        password=full_password,
        name="AGRO-AI Demo Operator",
    )
    full_org, _full_membership, full_org_created = _get_or_create_org(
        db,
        user=full_user,
        name=str(getattr(settings, "DEMO_FULL_ORGANIZATION_NAME", "AGRO-AI Demo Organization")),
        profile=DEMO_PROFILE,
    )
    _ensure_full_demo_portfolio(db, full_org)
    provision_non_customer_access(
        db,
        user=full_user,
        org=full_org,
        profile=DEMO_PROFILE,
        reason="Dedicated AGRO-AI launch/demo environment",
    )
    results.append(
        DemoIdentityResult(
            email=full_user.email,
            organization_id=full_org.id,
            organization_slug=full_org.slug,
            access_profile=DEMO_PROFILE,
            created_user=full_user_created,
            created_organization=full_org_created,
        )
    )

    free_user, free_user_created = _get_or_create_user(
        db,
        email=free_email,
        password=free_password,
        name="AGRO-AI Free Demo Operator",
    )
    free_org, _free_membership, free_org_created = _get_or_create_org(
        db,
        user=free_user,
        name=str(getattr(settings, "DEMO_FREE_ORGANIZATION_NAME", "AGRO-AI Free Demo")),
        profile="customer",
    )
    free_org.plan = "free"
    free_org.subscription_status = "inactive"
    free_org.subscription_source = "demo_seed_free_customer"
    free_metadata = dict(free_org.commercial_metadata_json or {})
    free_metadata.update(
        {
            "seed_source": DEMO_SEED_SOURCE,
            "access_profile": "customer",
            "billing_required": True,
            "operational_use": False,
            "demo_purpose": "show_real_free_plan_commercial_boundaries",
        }
    )
    free_org.commercial_metadata_json = free_metadata
    _ensure_free_demo_workspace(db, free_org)
    results.append(
        DemoIdentityResult(
            email=free_user.email,
            organization_id=free_org.id,
            organization_slug=free_org.slug,
            access_profile="customer",
            created_user=free_user_created,
            created_organization=free_org_created,
        )
    )

    db.commit()
    return results

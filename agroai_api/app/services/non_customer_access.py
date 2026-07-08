"""Server-authoritative provisioning for AGRO-AI internal and demo identities.

This module intentionally reuses the canonical commercial control plane. It does
not teach the browser how to bypass a paywall and it does not weaken customer
subscription checks. Explicitly authorized identities are provisioned as
non-customer organizations with durable entitlement overrides.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import EntitlementOverride, Organization, User, Workspace
from app.services.commercial_control import BASE_ENTITLEMENTS, FEATURE_STATES, PLAN_VERSION
from app.services.evaluation_seed import ensure_evaluation_context

CUSTOMER_PROFILE = "customer"
INTERNAL_PROFILE = "internal"
DEMO_PROFILE = "demo"
FULL_ACCESS_PROFILES = {INTERNAL_PROFILE, DEMO_PROFILE}
PROFILE_SOURCE_PREFIX = "access_profile:"


@dataclass(frozen=True)
class ProvisioningResult:
    profile: str
    organization_id: str
    changed: bool
    override_count: int


def _normalized_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _email_set(raw: str | None) -> set[str]:
    return {
        email
        for item in str(raw or "").replace(";", ",").split(",")
        if (email := _normalized_email(item))
    }


def configured_profile_for_email(email: str | None) -> str:
    """Return a profile only from server configuration; never from client input."""

    normalized = _normalized_email(email)
    if not normalized:
        return CUSTOMER_PROFILE
    if normalized in _email_set(getattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "")):
        return INTERNAL_PROFILE
    if normalized in _email_set(getattr(settings, "DEMO_FULL_ACCESS_EMAILS", "")):
        return DEMO_PROFILE
    return CUSTOMER_PROFILE


def configured_profile_for_user(user: User | None) -> str:
    return configured_profile_for_email(getattr(user, "email", None))


def access_profile_metadata(org: Organization) -> dict[str, Any]:
    raw_metadata = getattr(org, "commercial_metadata_json", None)
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    profile = str(metadata.get("access_profile") or CUSTOMER_PROFILE).strip().lower()
    if profile not in FULL_ACCESS_PROFILES:
        profile = CUSTOMER_PROFILE
    return {
        "profile": profile,
        "billing_required": profile == CUSTOMER_PROFILE,
        "demo_data_policy": metadata.get("demo_data_policy"),
    }


def _all_entitlement_keys() -> set[str]:
    return {key for values in BASE_ENTITLEMENTS.values() for key in values}


def _full_access_value(key: str) -> Any:
    if key == "intelligence.profile":
        return "institutional"
    if key.startswith("quota."):
        # Internal/demo capacity is deliberately unmetered. Customer plans remain
        # governed by their ordinary plan and contract limits.
        return None
    values = [plan_values.get(key) for plan_values in BASE_ENTITLEMENTS.values() if key in plan_values]
    if any(isinstance(value, str) and value in FEATURE_STATES for value in values):
        return "enabled"
    return BASE_ENTITLEMENTS.get("enterprise", {}).get(key)


def full_access_overrides() -> dict[str, Any]:
    return {key: _full_access_value(key) for key in sorted(_all_entitlement_keys())}


def _profile_override_rows(db: Session, org_id: str) -> dict[str, EntitlementOverride]:
    rows = (
        db.query(EntitlementOverride)
        .filter(
            EntitlementOverride.organization_id == org_id,
            EntitlementOverride.source.like(f"{PROFILE_SOURCE_PREFIX}%"),
        )
        .order_by(EntitlementOverride.created_at.asc())
        .all()
    )
    return {row.feature_key: row for row in rows}


def _snapshot_original_state(org: Organization, metadata: dict[str, Any]) -> None:
    if isinstance(metadata.get("pre_access_profile_state"), dict):
        return
    metadata["pre_access_profile_state"] = {
        "plan": org.plan,
        "plan_version": getattr(org, "plan_version", None),
        "subscription_status": org.subscription_status,
        "subscription_source": getattr(org, "subscription_source", None),
    }


def provision_non_customer_access(
    db: Session,
    *,
    user: User,
    org: Organization,
    profile: str,
    reason: str | None = None,
) -> ProvisioningResult:
    """Idempotently grant a server-controlled internal/demo organization profile."""

    normalized_profile = str(profile or "").strip().lower()
    if normalized_profile not in FULL_ACCESS_PROFILES:
        raise ValueError(f"Unsupported non-customer access profile: {profile!r}")

    metadata = dict(org.commercial_metadata_json or {})
    before = (
        org.plan,
        getattr(org, "plan_version", None),
        org.subscription_status,
        getattr(org, "subscription_source", None),
        metadata.get("access_profile"),
    )
    _snapshot_original_state(org, metadata)

    org.plan = "enterprise"
    org.plan_version = PLAN_VERSION
    org.subscription_status = "contracted"
    org.subscription_source = f"{PROFILE_SOURCE_PREFIX}{normalized_profile}"
    metadata.update(
        {
            "access_profile": normalized_profile,
            "billing_required": False,
            "provisioned_for_user_id": user.id,
            "provisioned_at": datetime.utcnow().isoformat() + "Z",
            "demo_data_policy": (
                "evaluation_sample_or_explicit_sandbox_only"
                if normalized_profile == DEMO_PROFILE
                else "internal_authorized_use"
            ),
        }
    )
    org.commercial_metadata_json = metadata

    existing = _profile_override_rows(db, org.id)
    source = f"{PROFILE_SOURCE_PREFIX}{normalized_profile}"
    overrides = full_access_overrides()
    changed = before != (
        org.plan,
        getattr(org, "plan_version", None),
        org.subscription_status,
        getattr(org, "subscription_source", None),
        normalized_profile,
    )

    for key, value in overrides.items():
        row = existing.get(key)
        if row is None:
            row = EntitlementOverride(
                organization_id=org.id,
                feature_key=key,
                value_json={"value": value},
                reason=reason or f"AGRO-AI {normalized_profile} full-access profile",
                source=source,
                valid_from=None,
                valid_until=None,
                created_by_user_id=user.id,
            )
            db.add(row)
            changed = True
            continue

        desired_json = {"value": value}
        if row.value_json != desired_json or row.source != source or row.valid_until is not None:
            row.value_json = desired_json
            row.source = source
            row.reason = reason or f"AGRO-AI {normalized_profile} full-access profile"
            row.valid_until = None
            row.created_by_user_id = user.id
            changed = True

    workspace = (
        db.query(Workspace)
        .filter(Workspace.organization_id == org.id)
        .order_by(Workspace.created_at.asc())
        .first()
    )
    ensure_evaluation_context(db, org, workspace)

    return ProvisioningResult(
        profile=normalized_profile,
        organization_id=org.id,
        changed=changed,
        override_count=len(overrides),
    )


def activate_configured_profile(
    db: Session,
    *,
    user: User,
    org: Organization,
) -> ProvisioningResult | None:
    """Activate only a server-allowlisted identity on an organization it owns."""

    if str(getattr(org, "owner_user_id", "") or "") != str(getattr(user, "id", "") or ""):
        return None
    profile = configured_profile_for_user(user)
    if profile not in FULL_ACCESS_PROFILES:
        return None
    return provision_non_customer_access(db, user=user, org=org, profile=profile)


def revoke_non_customer_access(db: Session, *, org: Organization) -> bool:
    """Remove profile overrides and restore the commercial state captured at first grant."""

    metadata = dict(org.commercial_metadata_json or {})
    profile = str(metadata.get("access_profile") or CUSTOMER_PROFILE)
    rows = (
        db.query(EntitlementOverride)
        .filter(
            EntitlementOverride.organization_id == org.id,
            EntitlementOverride.source.like(f"{PROFILE_SOURCE_PREFIX}%"),
        )
        .all()
    )
    for row in rows:
        db.delete(row)

    original = metadata.get("pre_access_profile_state") if isinstance(metadata.get("pre_access_profile_state"), dict) else {}
    org.plan = str(original.get("plan") or "free")
    org.plan_version = str(original.get("plan_version") or PLAN_VERSION)
    org.subscription_status = str(original.get("subscription_status") or "inactive")
    org.subscription_source = str(original.get("subscription_source") or "local")

    for key in (
        "access_profile",
        "billing_required",
        "provisioned_for_user_id",
        "provisioned_at",
        "demo_data_policy",
        "pre_access_profile_state",
    ):
        metadata.pop(key, None)
    org.commercial_metadata_json = metadata or None
    return profile in FULL_ACCESS_PROFILES or bool(rows)


def provision_many(
    db: Session,
    grants: Iterable[tuple[User, Organization, str]],
) -> list[ProvisioningResult]:
    return [
        provision_non_customer_access(db, user=user, org=org, profile=profile)
        for user, org, profile in grants
    ]

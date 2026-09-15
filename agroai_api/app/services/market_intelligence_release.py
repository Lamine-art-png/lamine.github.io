"""Server-authoritative release control for Market Intelligence."""
from __future__ import annotations

import logging
import os
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import EntitlementOverride, Organization, OrganizationMembership, User

logger = logging.getLogger(__name__)
RELEASE_STATES = {"disabled", "internal", "canary", "general"}
ROLLOUT_FEATURE_KEY = "market_intelligence.rollout"
_PRODUCTION_ENVS = {"production", "staging"}


def _csv(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _configured(name: str, default: str = "") -> str:
    """Read typed settings when present, otherwise an explicit environment value.

    Market Intelligence ships without forcing the large legacy Settings model
    to change. Deployment still receives normal environment-controlled rollout
    behavior and tests can exercise it deterministically.
    """
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return str(value)
    return str(os.getenv(name, default) or default)


def demo_fixtures_enabled() -> bool:
    value = _configured("MARKET_INTELLIGENCE_DEMO_FIXTURES_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _internal_emails() -> set[str]:
    return {item.lower() for item in (_csv(getattr(settings, "PLATFORM_ADMIN_EMAILS", "")) | _csv(getattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", "")))}


def configured_release_state() -> str:
    raw = _configured("MARKET_INTELLIGENCE_RELEASE_STATE", "").strip().lower()
    if raw in RELEASE_STATES:
        return raw
    if raw:
        logger.warning("Unknown MARKET_INTELLIGENCE_RELEASE_STATE %r; failing closed", raw)
        return "disabled"
    env = str(getattr(settings, "APP_ENV", "development") or "development").strip().lower()
    if env in _PRODUCTION_ENVS:
        return "internal" if _internal_emails() else "disabled"
    return "general"


def _org_has_internal_operator(db: Session, organization: Organization | None) -> bool:
    if organization is None or not _internal_emails():
        return False
    emails = (
        db.query(User.email)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.status == "active",
        )
        .all()
    )
    owner = db.query(User.email).filter(User.id == organization.owner_user_id).scalar()
    candidates = {str(row[0] or "").lower() for row in emails}
    if owner:
        candidates.add(str(owner).lower())
    return bool(candidates & _internal_emails())


def _override_cohort(db: Session, organization_id: str) -> str | None:
    row = (
        db.query(EntitlementOverride)
        .filter(
            EntitlementOverride.organization_id == organization_id,
            EntitlementOverride.feature_key == ROLLOUT_FEATURE_KEY,
        )
        .order_by(EntitlementOverride.created_at.desc())
        .first()
    )
    if row is None:
        return None
    value = row.value_json.get("value") if isinstance(row.value_json, dict) else row.value_json
    cohort = str(value or "").strip().lower()
    return cohort if cohort in {"internal", "canary"} else None


def organization_cohort(db: Session, organization: Organization | None) -> str:
    if organization is None:
        return "none"
    org_id = str(organization.id)
    if org_id in _csv(_configured("MARKET_INTELLIGENCE_INTERNAL_ORGANIZATION_IDS", "")) or _org_has_internal_operator(db, organization):
        return "internal"
    override = _override_cohort(db, org_id)
    if override == "internal":
        return "internal"
    if org_id in _csv(_configured("MARKET_INTELLIGENCE_CANARY_ORGANIZATION_IDS", "")) or override == "canary":
        return "canary"
    return "general"


def market_intelligence_access(db: Session, organization: Organization | None, *, user_email: str | None = None) -> tuple[bool, str, str]:
    state = configured_release_state()
    cohort = organization_cohort(db, organization)
    if str(user_email or "").strip().lower() in _internal_emails():
        cohort = "internal"
    if state == "disabled":
        return False, state, cohort
    if state == "internal":
        return cohort == "internal", state, cohort
    if state == "canary":
        return cohort in {"internal", "canary"}, state, cohort
    return True, state, cohort

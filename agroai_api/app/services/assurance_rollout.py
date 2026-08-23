"""Server-side release gate for Assurance Intelligence V2."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import Organization
from app.services.field_intelligence_rollout import internal_operator_email
from app.services.release_contract import runtime_build_sha

logger = logging.getLogger(__name__)

RELEASE_STATES = {"disabled", "internal", "canary", "general"}
# Founder-approved GA release, 2026-08-23. An explicit ASSURANCE_RELEASE_STATE
# always wins, so production can still be forced to disabled/internal/canary
# without another code release. Unset production reaches GA only on an
# immutable deployed build identity; staging remains fail-closed when unset.
PRODUCTION_DEFAULT_RELEASE_STATE = "general"


def _csv(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def configured_release_state() -> str:
    raw = str(getattr(settings, "ASSURANCE_RELEASE_STATE", "") or "").strip().lower()
    if raw in RELEASE_STATES:
        return raw
    if raw:
        logger.warning("Unknown ASSURANCE_RELEASE_STATE %r; treating as disabled", raw)
        return "disabled"
    environment = str(getattr(settings, "APP_ENV", "development") or "").strip().lower()
    if environment == "production":
        # GA is source-controlled, but only a real immutable deployment may
        # inherit it. Local/test processes pretending to be production remain
        # disabled, preserving the fail-closed pre-deployment contract.
        return PRODUCTION_DEFAULT_RELEASE_STATE if runtime_build_sha() else "disabled"
    if environment == "staging":
        return "disabled"
    return "general"


def assurance_access(
    db: Session,
    organization: Organization | None,
    *,
    user_email: str | None = None,
) -> tuple[bool, str, str]:
    """Return ``(allowed, release_state, cohort)`` from server-owned values."""
    del db  # reserved for audited runtime overrides without changing callers
    state = configured_release_state()
    org_id = str(organization.id) if organization else ""
    if internal_operator_email(user_email) or org_id in _csv(settings.ASSURANCE_INTERNAL_ORGANIZATION_IDS):
        cohort = "internal"
    elif org_id in _csv(settings.ASSURANCE_CANARY_ORGANIZATION_IDS):
        cohort = "canary"
    else:
        cohort = "general"
    if state == "disabled":
        return False, state, cohort
    if state == "internal":
        return cohort == "internal", state, cohort
    if state == "canary":
        return cohort in {"internal", "canary"}, state, cohort
    return True, state, cohort

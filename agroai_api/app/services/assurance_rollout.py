"""Fail-closed, server-side release gate for Assurance Intelligence V2."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.saas import Organization
from app.services.field_intelligence_rollout import internal_operator_email

logger = logging.getLogger(__name__)

RELEASE_STATES = {"disabled", "internal", "canary", "general"}
PRODUCTION_ENVS = {"production", "staging"}


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
    return "disabled" if environment in PRODUCTION_ENVS else "general"


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

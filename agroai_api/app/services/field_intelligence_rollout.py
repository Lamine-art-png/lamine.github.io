"""Field Intelligence controlled-rollout control plane.

Server-side release states — never frontend gates:

* ``disabled``  — nobody can use Field Intelligence.
* ``internal``  — only internal-cohort organizations and configured AGRO-AI
  internal/platform-admin operators.
* ``canary``    — internal + canary-allowlisted organizations.
* ``general``   — all authorized organizations (subject to entitlements), and
  only when the exact-SHA release alignment holds.

The *default* state comes from deployment configuration
(``FIELD_INTELLIGENCE_RELEASE_STATE``). An unset value remains fail-closed in
production/staging unless an explicit internal operator email list is already
configured, in which case the default is ``internal``. This allows the existing
AGRO-AI operations account to use a newly shipped feature without silently
opening it to customers. Two database-resident runtime flags provide audited,
redeploy-free control:

* the emergency kill switch (always wins, immediately);
* an explicit release-state override (platform-admin only, audited).

Canary/internal membership comes from secure configuration CSVs or from a
per-organization ``field_intelligence.rollout`` entitlement override — never
from identifiers hardcoded in source. A plan update can never grant
``general``: entitlement overrides may only place an organization in the
``internal`` or ``canary`` cohort.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.field_intelligence import FieldRuntimeFlag
from app.models.saas import (
    EntitlementOverride,
    Organization,
    OrganizationMembership,
    SecurityAuditEvent,
    User,
)

logger = logging.getLogger(__name__)

RELEASE_STATES = ("disabled", "internal", "canary", "general")
KILL_SWITCH_FLAG = "field_intelligence.kill_switch"
RELEASE_OVERRIDE_FLAG = "field_intelligence.release_state_override"
ROLLOUT_FEATURE_KEY = "field_intelligence.rollout"
_OVERRIDE_COHORTS = {"internal", "canary"}
_PRODUCTION_ENVS = {"production", "staging"}


def _csv(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _configured_internal_operator_emails() -> set[str]:
    return {
        item.lower()
        for item in (
            _csv(getattr(settings, "PLATFORM_ADMIN_EMAILS", ""))
            | _csv(getattr(settings, "INTERNAL_FULL_ACCESS_EMAILS", ""))
        )
    }


def configured_release_state() -> str:
    raw = str(getattr(settings, "FIELD_INTELLIGENCE_RELEASE_STATE", "") or "").strip().lower()
    if raw in RELEASE_STATES:
        return raw
    if raw:
        logger.warning("Unknown FIELD_INTELLIGENCE_RELEASE_STATE %r; treating as disabled", raw)
        return "disabled"
    env = str(getattr(settings, "APP_ENV", "development") or "").strip().lower()
    if env in _PRODUCTION_ENVS:
        return "internal" if _configured_internal_operator_emails() else "disabled"
    return "general"


def internal_operator_email(email: str | None) -> bool:
    return str(email or "").strip().lower() in _configured_internal_operator_emails()


def _organization_has_internal_operator(db: Session, organization: Organization | None) -> bool:
    """Resolve the cohort from server-owned user and membership records.

    Field Intelligence routes already pass a canonical authenticated
    organization. This query allows that organization's configured AGRO-AI
    operator account to activate the internal release without trusting a browser
    claim or hardcoding an organization id.
    """
    if organization is None:
        return False
    allowed = _configured_internal_operator_emails()
    if not allowed:
        return False
    owner_email = (
        db.query(User.email)
        .filter(User.id == organization.owner_user_id)
        .scalar()
    )
    if internal_operator_email(owner_email):
        return True
    member_emails = (
        db.query(User.email)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.status == "active",
        )
        .all()
    )
    return any(internal_operator_email(row[0]) for row in member_emails)


def _flag(db: Session, key: str) -> dict | None:
    row = db.get(FieldRuntimeFlag, key)
    if row is None:
        return None
    value = row.value_json
    return value if isinstance(value, dict) else {"value": value}


def kill_switch_active(db: Session) -> bool:
    flag = _flag(db, KILL_SWITCH_FLAG)
    return bool(flag and flag.get("active"))


def release_state_override(db: Session) -> str | None:
    flag = _flag(db, RELEASE_OVERRIDE_FLAG)
    if not flag:
        return None
    value = str(flag.get("state") or "").strip().lower()
    return value if value in RELEASE_STATES else None


def effective_release_state(db: Session) -> str:
    if kill_switch_active(db):
        return "disabled"
    state = release_state_override(db) or configured_release_state()
    env = str(getattr(settings, "APP_ENV", "development") or "").strip().lower()
    if state == "general" and env in _PRODUCTION_ENVS:
        from app.services.field_release_proof import release_alignment

        alignment = release_alignment(db)
        if not alignment.get("aligned", False):
            logger.error(
                "field-intelligence release misalignment blocks general activation: %s",
                alignment.get("mismatches"),
            )
            return "canary"
    return state


def _override_cohort(db: Session, organization_id: str) -> str | None:
    row = (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == organization_id)
        .filter(EntitlementOverride.feature_key == ROLLOUT_FEATURE_KEY)
        .order_by(EntitlementOverride.created_at.desc())
        .first()
    )
    if not row:
        return None
    value = row.value_json.get("value") if isinstance(row.value_json, dict) else row.value_json
    cohort = str(value or "").strip().lower()
    return cohort if cohort in _OVERRIDE_COHORTS else None


def organization_cohort(db: Session, organization: Organization | None) -> str:
    if organization is None:
        return "none"
    org_id = str(organization.id)
    if org_id in _csv(getattr(settings, "FIELD_INTERNAL_ORGANIZATION_IDS", "")):
        return "internal"
    if _organization_has_internal_operator(db, organization):
        return "internal"
    override = _override_cohort(db, org_id)
    if override == "internal":
        return "internal"
    if org_id in _csv(getattr(settings, "FIELD_CANARY_ORGANIZATION_IDS", "")) or override == "canary":
        return "canary"
    return "general"


def field_intelligence_access(
    db: Session,
    organization: Organization | None,
    *,
    user_email: str | None = None,
) -> tuple[bool, str, str]:
    """Return ``(allowed, effective_state, cohort)`` for this request."""
    state = effective_release_state(db)
    cohort = organization_cohort(db, organization)
    if internal_operator_email(user_email):
        cohort = "internal"
    if state == "disabled":
        return False, state, cohort
    if state == "internal":
        return cohort == "internal", state, cohort
    if state == "canary":
        return cohort in {"internal", "canary"}, state, cohort
    return True, state, cohort


def _audit_rollout_change(
    db: Session, *, action: str, actor_user_id: str | None, detail: dict[str, Any]
) -> None:
    db.add(
        SecurityAuditEvent(
            id=str(uuid.uuid4()),
            user_id=actor_user_id,
            event_type="field_intelligence_rollout_change",
            outcome=action,
            metadata_json=detail,
            created_at=datetime.utcnow(),
        )
    )


def set_kill_switch(db: Session, *, active: bool, actor_user_id: str | None, reason: str | None = None) -> dict:
    row = db.get(FieldRuntimeFlag, KILL_SWITCH_FLAG)
    value = {"active": bool(active), "reason": (reason or "")[:500]}
    if row is None:
        row = FieldRuntimeFlag(key=KILL_SWITCH_FLAG, value_json=value, updated_by=actor_user_id)
        db.add(row)
    else:
        row.value_json = value
        row.updated_by = actor_user_id
        row.updated_at = datetime.utcnow()
    _audit_rollout_change(
        db,
        action="kill_switch_enabled" if active else "kill_switch_disabled",
        actor_user_id=actor_user_id,
        detail={"reason": (reason or "")[:500]},
    )
    db.commit()
    if active:
        logger.critical("FIELD INTELLIGENCE EMERGENCY KILL SWITCH ACTIVATED (actor=%s)", actor_user_id)
    from app.services.field_intelligence_metrics import record_emergency_disable

    record_emergency_disable(active=active)
    return {"kill_switch": bool(active)}


def set_release_override(
    db: Session, *, state: str | None, actor_user_id: str | None, reason: str | None = None
) -> dict:
    if state is not None:
        state = str(state).strip().lower()
        if state not in RELEASE_STATES:
            raise ValueError(f"invalid release state: {state}")
    row = db.get(FieldRuntimeFlag, RELEASE_OVERRIDE_FLAG)
    if state is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(FieldRuntimeFlag(key=RELEASE_OVERRIDE_FLAG,
                                value_json={"state": state, "reason": (reason or "")[:500]},
                                updated_by=actor_user_id))
    else:
        row.value_json = {"state": state, "reason": (reason or "")[:500]}
        row.updated_by = actor_user_id
        row.updated_at = datetime.utcnow()
    _audit_rollout_change(
        db,
        action=f"release_override_{state or 'cleared'}",
        actor_user_id=actor_user_id,
        detail={"state": state, "reason": (reason or "")[:500]},
    )
    db.commit()
    return {"release_state_override": state}


def rollout_status(db: Session) -> dict:
    from app.services.field_release_proof import release_alignment

    return {
        "configured_state": configured_release_state(),
        "override_state": release_state_override(db),
        "kill_switch": kill_switch_active(db),
        "effective_state": effective_release_state(db),
        "release_alignment": release_alignment(db),
    }

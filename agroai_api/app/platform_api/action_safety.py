from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import ActionSafetyConfiguration
from app.platform_api.principal import PlatformPrincipal


@dataclass(frozen=True)
class PhysicalActionSafetyInput:
    provider: str
    command_type: str
    resource_id: str | None = None
    connection_id: str | None = None
    approval_confirmed: bool = False
    equipment_state_observed_at: datetime | None = None
    provider_write_capability: bool = False
    commercial_entitlement_verified: bool = False
    ai_recommendation_only: bool = False


def evaluate_physical_action_safety(
    db: Session,
    *,
    principal: PlatformPrincipal,
    request: PhysicalActionSafetyInput,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic deny-first safety gate for future physical commands.

    The private beta never executes physical actions. This evaluator records the
    individual gates so tests and future rollout work have one auditable policy
    boundary instead of scattered route checks.
    """
    current_time = now or datetime.utcnow()
    blockers: list[str] = []

    if not bool(getattr(settings, "VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED", False)):
        blockers.append("global_write_disabled")
    if principal.environment != "live":
        blockers.append("live_environment_required")
    if "actions:execute" not in principal.scopes:
        blockers.append("actions_execute_scope_required")
    if not request.provider_write_capability:
        blockers.append("provider_write_capability_unconfirmed")
    if not request.commercial_entitlement_verified:
        blockers.append("commercial_entitlement_required")
    if not request.approval_confirmed:
        blockers.append("explicit_customer_approval_required")
    if request.ai_recommendation_only:
        blockers.append("ai_recommendation_cannot_authorize_execution")
    if request.equipment_state_observed_at is None:
        blockers.append("fresh_equipment_state_required")
    elif request.equipment_state_observed_at < current_time - timedelta(minutes=15):
        blockers.append("equipment_state_stale")

    blockers.extend(_configured_blockers(db, principal=principal, request=request))

    return {
        "allowed": False,
        "provider": request.provider,
        "command_type": request.command_type,
        "blockers": sorted(set(blockers or ["physical_action_disabled"])),
        "physical_execution_enabled": False,
    }


def _configured_blockers(
    db: Session,
    *,
    principal: PlatformPrincipal,
    request: PhysicalActionSafetyInput,
) -> list[str]:
    rows = (
        db.query(ActionSafetyConfiguration)
        .filter(ActionSafetyConfiguration.organization_id == principal.organization_id)
        .filter(ActionSafetyConfiguration.disabled.is_(True))
        .all()
    )
    blockers: list[str] = []
    for row in rows:
        if row.command_type not in {"*", request.command_type}:
            continue
        if row.api_project_id and row.api_project_id != principal.api_project_id:
            continue
        if row.connection_id and row.connection_id != request.connection_id:
            continue
        if row.resource_id and row.resource_id != request.resource_id:
            continue
        if row.resource_id:
            blockers.append("resource_write_disabled")
        elif row.connection_id:
            blockers.append("connection_write_disabled")
        elif row.api_project_id:
            blockers.append("project_write_disabled")
        else:
            blockers.append("organization_write_disabled")
    return blockers

"""Effective entitlement resolution and compatibility checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.saas import EntitlementOverride, Organization, Workspace
from app.services.product_plans import (
    ACTIVE_SUBSCRIPTION_STATUSES,
    PAID_PLAN_CODES,
    PLAN_CATALOG,
    PLAN_VERSION,
    recommended_plan_for_feature,
    normalize_plan_code,
)


ENABLED_STATES = {"enabled", "preview"}
VARIABLE_COST_FEATURES = {
    "evidence.upload",
    "reports.generate",
    "reports.pdf_export",
    "reports.email_delivery",
    "connectors.live",
    "connectors.provider.wiseconn",
    "connectors.provider.talgil",
    "connectors.provider.openet",
    "agents.plan",
    "agents.execute_approval_gated",
    "intelligence.deep_analysis",
    "intelligence.cross_workspace",
    "network.cross_workspace_intelligence",
}
VARIABLE_COST_QUOTAS = {
    "quota.evidence_upload.monthly",
    "quota.ai_action.monthly",
    "quota.agent_run.monthly",
    "quota.report_export.monthly",
}


@dataclass(frozen=True)
class PlanLimits:
    max_workspaces: int
    max_users: int
    max_agent_runs_per_month: int
    max_evidence_uploads_per_month: int
    can_export_reports: bool
    can_use_live_integrations: bool
    can_invite_team: bool
    can_create_live_assurance_passports: bool
    can_access_billing_portal: bool
    max_ai_actions_per_month: int = 0
    max_report_exports_per_month: int = 0


@dataclass(frozen=True)
class EffectiveEntitlements:
    plan: str
    plan_version: str
    subscription_status: str
    customer_class: str
    values: dict[str, Any]
    explanations: dict[str, str]


def _feature_state(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("state", "unavailable"))
    if value is True:
        return "enabled"
    if value is False or value is None:
        return "locked"
    return "enabled"


def _is_enabled(value: Any) -> bool:
    return _feature_state(value) in ENABLED_STATES


def _apply_subscription_restrictions(org: Organization, plan: str, values: dict[str, Any], explanations: dict[str, str]) -> None:
    if plan not in PAID_PLAN_CODES or org.subscription_status in ACTIVE_SUBSCRIPTION_STATUSES:
        return
    for feature_key in VARIABLE_COST_FEATURES:
        if feature_key in values and _is_enabled(values[feature_key]):
            values[feature_key] = {"state": "locked"}
            explanations[feature_key] = f"restricted because subscription_status={org.subscription_status}"
    for quota_key in VARIABLE_COST_QUOTAS:
        if quota_key in values:
            values[quota_key] = 0
            explanations[quota_key] = f"restricted because subscription_status={org.subscription_status}"


def _active_overrides(db: Session, org: Organization, at_time: datetime) -> list[EntitlementOverride]:
    return (
        db.query(EntitlementOverride)
        .filter(EntitlementOverride.organization_id == org.id)
        .all()
    )


def resolve_effective_entitlements(
    organization: Organization,
    db: Session | None = None,
    workspace: Workspace | None = None,
    user: Any | None = None,
    at_time: datetime | None = None,
) -> EffectiveEntitlements:
    del workspace, user
    now = at_time or datetime.utcnow()
    plan = normalize_plan_code(organization.plan)
    definition = PLAN_CATALOG[plan]
    values = dict(definition.entitlements)
    explanations = {key: f"base plan {plan}@{definition.version}" for key in values}

    if db is not None:
        for override in _active_overrides(db, organization, now):
            if override.valid_from and override.valid_from > now:
                continue
            if override.valid_until and override.valid_until <= now:
                continue
            values[override.feature_key] = override.value_json
            explanations[override.feature_key] = f"override:{override.source}"

    _apply_subscription_restrictions(organization, plan, values, explanations)
    return EffectiveEntitlements(
        plan=plan,
        plan_version=getattr(organization, "plan_version", None) or PLAN_VERSION,
        subscription_status=organization.subscription_status,
        customer_class=getattr(organization, "customer_class", None) or "individual_operator",
        values=values,
        explanations=explanations,
    )


def get_value(org: Organization, feature_key: str, db: Session | None = None, default: Any = None) -> Any:
    return resolve_effective_entitlements(org, db=db).values.get(feature_key, default)


def has_feature(org: Organization, feature_key: str, db: Session | None = None) -> bool:
    return _is_enabled(get_value(org, feature_key, db=db))


def explain_entitlement(org: Organization, feature_key: str, db: Session | None = None) -> dict[str, Any]:
    effective = resolve_effective_entitlements(org, db=db)
    value = effective.values.get(feature_key)
    return {
        "feature": feature_key,
        "value": value,
        "state": _feature_state(value),
        "plan": effective.plan,
        "plan_version": effective.plan_version,
        "subscription_status": effective.subscription_status,
        "reason": effective.explanations.get(feature_key, "not included"),
        "recommended_plan": recommended_plan_for_feature(feature_key),
    }


def require_feature(org: Organization, feature_key: str, db: Session | None = None) -> None:
    explanation = explain_entitlement(org, feature_key, db=db)
    if explanation["state"] in ENABLED_STATES:
        return
    recommended = explanation.get("recommended_plan")
    message = f"{feature_key} is not enabled for this organization."
    if recommended:
        message = f"{feature_key} is included in {PLAN_CATALOG[recommended].name} and above."
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "upgrade_required",
            "feature": feature_key,
            "recommended_plan": recommended,
            "message": message,
        },
    )


def get_plan_limits(plan: str | None) -> PlanLimits:
    class _Org:
        subscription_status = "active"
        customer_class = "individual_operator"
        plan_version = PLAN_VERSION

        def __init__(self, plan_value: str | None):
            self.plan = plan_value or "free"

    effective = resolve_effective_entitlements(_Org(plan))
    values = effective.values
    return PlanLimits(
        max_workspaces=int(values.get("quota.workspaces", 1) or 0),
        max_users=int(values.get("quota.seats", 1) or 0),
        max_agent_runs_per_month=int(values.get("quota.agent_run.monthly", 0) or 0),
        max_evidence_uploads_per_month=int(values.get("quota.evidence_upload.monthly", 0) or 0),
        can_export_reports=_is_enabled(values.get("reports.pdf_export")),
        can_use_live_integrations=_is_enabled(values.get("connectors.live")),
        can_invite_team=_is_enabled(values.get("team.invite")),
        can_create_live_assurance_passports=_is_enabled(values.get("agents.execute_approval_gated")),
        can_access_billing_portal=True,
        max_ai_actions_per_month=int(values.get("quota.ai_action.monthly", 0) or 0),
        max_report_exports_per_month=int(values.get("quota.report_export.monthly", 0) or 0),
    )


def serialize_entitlements(org: Organization, db: Session | None = None) -> dict[str, Any]:
    effective = resolve_effective_entitlements(org, db=db)
    limits = asdict(get_plan_limits(effective.plan))
    limits["plan"] = effective.plan
    limits["plan_version"] = effective.plan_version
    limits["customer_class"] = effective.customer_class
    limits["subscription_status"] = effective.subscription_status
    limits["features"] = effective.values
    return limits


def require_owner_or_admin(role: str) -> None:
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_or_admin_required", "message": "Owner or admin access is required."},
        )


def require_subscription_active(org: Organization) -> None:
    plan = normalize_plan_code(org.plan)
    if plan in PAID_PLAN_CODES and org.subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "subscription_inactive", "message": "An active subscription or contract is required."},
        )


def require_workspace_mode(workspace: Workspace, mode: str) -> None:
    if workspace.mode != mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "live_workspace_required", "message": "This action requires a live workspace."},
        )


def assert_can_create_workspace(db: Session, org: Organization, mode: str) -> None:
    from app.models.saas import Workspace

    effective = resolve_effective_entitlements(org, db=db)
    limit = int(effective.values.get("quota.workspaces", 1) or 0)
    current = db.query(Workspace).filter(Workspace.organization_id == org.id).count()
    if current >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "Workspace limit reached for this plan."},
        )
    if mode == "live":
        require_feature(org, "connectors.live", db=db)
    if normalize_plan_code(org.plan) in PAID_PLAN_CODES:
        require_subscription_active(org)


def assert_can_upload_evidence(db: Session, org: Organization) -> None:
    require_feature(org, "evidence.upload", db=db)


def assert_can_run_agent(db: Session, org: Organization) -> None:
    require_feature(org, "agents.plan", db=db)


def assert_can_export_reports(org: Organization, db: Session | None = None) -> None:
    require_feature(org, "reports.pdf_export", db=db)

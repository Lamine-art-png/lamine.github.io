"""Compatibility entitlements plus canonical commercial runtime enforcement."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.saas import Organization, OrganizationMembership, UsageEvent, Workspace
from app.services.commercial_control import (
    canonical_plan,
    customer_safe_entitlement_payload,
    get_limit,
    require_feature,
)
from app.services.product_plans import plan_by_id


@dataclass(frozen=True)
class PlanLimits:
    max_workspaces: int
    max_users: int
    max_uploads_monthly: int
    max_agro_ai_messages_monthly: int
    can_generate_pdf: bool
    can_generate_compliance_packet: bool
    can_use_connectors: bool
    can_invite_team: bool
    can_access_admin_requests: bool
    can_access_network_rollups: bool
    can_access_enterprise_security: bool
    support_level: str
    can_export_reports: bool
    can_use_live_integrations: bool
    can_create_live_assurance_passports: bool
    can_access_billing_portal: bool


# Compatibility surface for older route/tests. Runtime quota and feature decisions use
# commercial_control.resolve_effective_entitlements instead of these fixed values.
PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(1, 1, 10, 25, False, False, False, False, False, False, False, "basic", False, False, False, True),
    "professional": PlanLimits(5, 3, 500, 500, True, True, True, False, False, False, False, "standard", True, True, True, True),
    "team": PlanLimits(25, 10, 2500, 2500, True, True, True, True, True, False, False, "priority", True, True, True, True),
    "network": PlanLimits(50, 25, 10000, 10000, True, True, True, True, True, True, False, "priority", True, True, True, True),
    "enterprise": PlanLimits(10000, 10000, 100000, 100000, True, True, True, True, True, True, True, "enterprise", True, True, True, True),
}
for alias in ("pilot", "assurance_audit", "waterops", "assurance", "pro"):
    PLAN_LIMITS[alias] = PLAN_LIMITS[canonical_plan(alias)]


def get_plan_limits(plan: str | None) -> PlanLimits:
    return PLAN_LIMITS[canonical_plan(plan)]


def serialize_entitlements(org: Organization, db: Session | None = None) -> dict:
    limits = asdict(get_plan_limits(org.plan))
    plan = plan_by_id(org.plan)
    limits.update(
        {
            "plan": plan["id"],
            "plan_name": plan["name"],
            "subscription_status": org.subscription_status,
            "max_agent_runs_per_month": limits["max_agro_ai_messages_monthly"],
            "max_evidence_uploads_per_month": limits["max_uploads_monthly"],
            "can_run_agro_ai": limits["max_agro_ai_messages_monthly"] > 0,
            "upgrade_targets": {
                "pdf_reports": "professional",
                "compliance_packets": "professional",
                "connectors": "professional",
                "team_invites": "team",
                "admin_requests": "team",
                "network_rollups": "network",
                "enterprise_security": "enterprise",
            },
        }
    )
    if db is not None:
        control = customer_safe_entitlement_payload(db, org)
        limits.update(
            {
                "plan_version": control["plan_version"],
                "customer_class": control["customer_class"],
                "organization_type": control["organization_type"],
                "intelligence_profile": control["intelligence_profile"],
                "capabilities": control["capabilities"],
                "quotas": control["quotas"],
            }
        )
    return limits


def require_owner_or_admin(role: str) -> None:
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_or_admin_required", "message": "Owner or admin access is required."},
        )


def require_subscription_active(org: Organization) -> None:
    if canonical_plan(org.plan) != "free" and org.subscription_status not in {"active", "trialing", "contracted"}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "subscription_inactive", "message": "An active commercial subscription or contract is required."},
        )


def require_workspace_mode(workspace: Workspace, mode: str) -> None:
    if workspace.mode != mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "live_workspace_required", "message": "This action requires a live workspace."},
        )


def count_monthly_usage(db: Session, organization_id: str, event_type: str) -> int:
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    value = (
        db.query(func.coalesce(func.sum(UsageEvent.quantity), 0))
        .filter(
            UsageEvent.organization_id == organization_id,
            UsageEvent.event_type == event_type,
            UsageEvent.created_at >= month_start,
        )
        .scalar()
    )
    return int(value or 0)


def organization_user_count(db: Session, org: Organization) -> int:
    return int(
        db.query(func.count(OrganizationMembership.id))
        .filter(OrganizationMembership.organization_id == org.id)
        .scalar()
        or 0
    )


def assert_can_create_workspace(db: Session, org: Organization, mode: str) -> None:
    current = db.query(Workspace).filter(Workspace.organization_id == org.id).count()
    limit = get_limit(db, org, "quota.workspace")
    if limit is not None and current >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "metric": "workspace", "limit": limit, "message": "Workspace limit reached for this plan."},
        )
    if mode == "live":
        require_feature(db, org, "connectors.live", recommended_plan="professional")


def assert_can_upload_evidence(db: Session, org: Organization) -> None:
    from app.services.quota import committed_usage, quota_limit

    require_feature(db, org, "evidence.upload")
    limit = quota_limit(db, org, "evidence_upload")
    if limit is not None and committed_usage(db, org, "evidence_upload") >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "quota_exceeded", "metric": "evidence_upload", "limit": limit, "message": "Evidence upload quota reached."},
        )


def assert_can_run_agent(db: Session, org: Organization) -> None:
    from app.services.quota import committed_usage, quota_limit

    require_feature(db, org, "intelligence.ask")
    limit = quota_limit(db, org, "ai_action")
    if limit is not None and committed_usage(db, org, "ai_action") >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "quota_exceeded", "metric": "ai_action", "limit": limit, "message": "AGRO-AI intelligence quota reached."},
        )


def assert_can_export_reports(org: Organization, db: Session | None = None) -> None:
    if db is not None:
        require_feature(db, org, "reports.pdf_export", recommended_plan="professional")
        return
    if not get_plan_limits(org.plan).can_generate_pdf:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "PDF reports are included in Professional.", "recommended_plan": "professional"},
        )


def assert_can_invite_team(org: Organization, db: Session | None = None) -> None:
    if db is not None:
        require_feature(db, org, "team.invite", recommended_plan="team")
        return
    if not get_plan_limits(org.plan).can_invite_team:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Team invitations are available on the Team plan.", "recommended_plan": "team"},
        )


def assert_can_access_admin_requests(org: Organization, db: Session | None = None) -> None:
    if db is not None:
        require_feature(db, org, "admin.requests", recommended_plan="team")
        return
    if not get_plan_limits(org.plan).can_access_admin_requests:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Admin request inbox is available on the Team plan.", "recommended_plan": "team"},
        )


def assert_can_use_connectors(org: Organization, db: Session | None = None) -> None:
    if db is not None:
        require_feature(db, org, "connectors.live", recommended_plan="professional")
        return
    if not get_plan_limits(org.plan).can_use_connectors:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Live connectors are included in Professional.", "recommended_plan": "professional"},
        )

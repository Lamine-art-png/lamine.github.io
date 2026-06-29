"""Plan limits and entitlement checks for SaaS organizations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.saas import Organization, OrganizationMembership, UsageEvent, Workspace
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


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(1, 1, 10, 25, False, False, False, False, False, False, False, "basic", False, False, False, True),
    "professional": PlanLimits(5, 3, 500, 500, True, True, True, False, False, False, False, "standard", True, True, True, True),
    "team": PlanLimits(25, 10, 2500, 2500, True, True, True, True, True, False, False, "priority", True, True, True, True),
    "network": PlanLimits(50, 25, 10000, 10000, True, True, True, True, True, True, False, "priority", True, True, True, True),
    "enterprise": PlanLimits(10000, 10000, 100000, 100000, True, True, True, True, True, True, True, "enterprise", True, True, True, True),
    "pilot": PlanLimits(1, 1, 10, 25, False, False, False, False, False, False, False, "basic", False, False, False, True),
    "assurance_audit": PlanLimits(5, 3, 500, 500, True, True, True, False, False, False, False, "standard", True, True, True, True),
    "waterops": PlanLimits(5, 3, 500, 500, True, True, True, False, False, False, False, "standard", True, True, True, True),
    "assurance": PlanLimits(25, 10, 2500, 2500, True, True, True, True, True, False, False, "priority", True, True, True, True),
    "pro": PlanLimits(5, 3, 500, 500, True, True, True, False, False, False, False, "standard", True, True, True, True),
}


def get_plan_limits(plan: str | None) -> PlanLimits:
    return PLAN_LIMITS.get((plan or "free").lower(), PLAN_LIMITS["free"])


def serialize_entitlements(org: Organization) -> dict:
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
    return limits


def require_owner_or_admin(role: str) -> None:
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_or_admin_required", "message": "Owner or admin access is required."},
        )


def require_subscription_active(org: Organization) -> None:
    if get_plan_limits(org.plan).support_level != "basic" and org.subscription_status not in {"active", "trialing"}:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "subscription_inactive", "message": "An active subscription is required."},
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
    limits = get_plan_limits(org.plan)
    current = db.query(Workspace).filter(Workspace.organization_id == org.id).count()
    if current >= limits.max_workspaces:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "Workspace limit reached for this plan."},
        )
    if mode == "live" and not limits.can_use_live_integrations:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "plan_required", "message": "Live workspaces require a paid plan."},
        )
    if limits.support_level != "basic":
        require_subscription_active(org)


def assert_can_upload_evidence(db: Session, org: Organization) -> None:
    limits = get_plan_limits(org.plan)
    if count_monthly_usage(db, org.id, "evidence_upload") >= limits.max_uploads_monthly:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "Evidence upload limit reached for this plan."},
        )


def assert_can_run_agent(db: Session, org: Organization) -> None:
    limits = get_plan_limits(org.plan)
    if limits.max_agro_ai_messages_monthly <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "plan_required", "message": "AGRO-AI messages require a paid plan."},
        )
    if count_monthly_usage(db, org.id, "agent_run") >= limits.max_agro_ai_messages_monthly:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "AGRO-AI message limit reached for this plan."},
        )


def assert_can_export_reports(org: Organization) -> None:
    if not get_plan_limits(org.plan).can_generate_pdf:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "PDF reports are included in Professional.", "recommended_plan": "professional"},
        )


def assert_can_invite_team(org: Organization) -> None:
    if not get_plan_limits(org.plan).can_invite_team:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Team invitations are available on the Team plan.", "recommended_plan": "team"},
        )


def assert_can_access_admin_requests(org: Organization) -> None:
    if not get_plan_limits(org.plan).can_access_admin_requests:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Admin request inbox is available on the Team plan.", "recommended_plan": "team"},
        )


def assert_can_use_connectors(org: Organization) -> None:
    if not get_plan_limits(org.plan).can_use_connectors:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "upgrade_required", "message": "Connectors are included in Professional.", "recommended_plan": "professional"},
        )

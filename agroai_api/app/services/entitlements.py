"""Plan limits and entitlement checks for SaaS organizations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.saas import Organization, UsageEvent, Workspace


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


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(1, 1, 0, 0, False, False, False, False, True),
    "pilot": PlanLimits(3, 3, 50, 100, True, False, True, False, True),
    "pro": PlanLimits(25, 15, 500, 1000, True, True, True, True, True),
    "enterprise": PlanLimits(10_000, 10_000, 100_000, 100_000, True, True, True, True, True),
}


def get_plan_limits(plan: str | None) -> PlanLimits:
    return PLAN_LIMITS.get((plan or "free").lower(), PLAN_LIMITS["free"])


def serialize_entitlements(org: Organization) -> dict:
    limits = asdict(get_plan_limits(org.plan))
    limits["plan"] = org.plan
    limits["subscription_status"] = org.subscription_status
    return limits


def require_owner_or_admin(role: str) -> None:
    if role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "owner_or_admin_required", "message": "Owner or admin access is required."},
        )


def require_subscription_active(org: Organization) -> None:
    if org.plan in {"pilot", "pro", "enterprise"} and org.subscription_status not in {"active", "trialing"}:
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
    require_subscription_active(org)


def assert_can_upload_evidence(db: Session, org: Organization) -> None:
    limits = get_plan_limits(org.plan)
    if limits.max_evidence_uploads_per_month <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "plan_required", "message": "Evidence uploads require a paid plan."},
        )
    if count_monthly_usage(db, org.id, "evidence_upload") >= limits.max_evidence_uploads_per_month:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "Evidence upload limit reached for this plan."},
        )


def assert_can_run_agent(db: Session, org: Organization) -> None:
    limits = get_plan_limits(org.plan)
    if limits.max_agent_runs_per_month <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "plan_required", "message": "Agent runs require a paid plan."},
        )
    if count_monthly_usage(db, org.id, "agent_run") >= limits.max_agent_runs_per_month:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "limit_reached", "message": "Agent run limit reached for this plan."},
        )


def assert_can_export_reports(org: Organization) -> None:
    if not get_plan_limits(org.plan).can_export_reports:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "plan_required", "message": "Report exports require a paid plan."},
        )

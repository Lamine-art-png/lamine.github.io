"""Server-authoritative Platform API program and entitlement policy."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.organization_access import organization_access_allowed
from app.models.platform_product import (
    PlatformApiPlan,
    PlatformApiSubscription,
    PlatformLiveAccessRequest,
    PlatformProgramEnrollment,
)
from app.models.saas import Organization


PROGRAMS = frozenset(
    {
        "internal",
        "developer_private_beta",
        "developer_self_service",
        "strategic_partner",
        "enterprise_custom",
    }
)
ACTIVE_ENROLLMENT_STATUSES = frozenset({"active", "approved"})
API_ACCESS_SUBSCRIPTION_STATES = frozenset({"free", "trialing", "active", "past_due", "grace", "enterprise_contract"})
LIVE_ACCESS_SUBSCRIPTION_STATES = frozenset({"trialing", "active", "enterprise_contract"})


def active_enrollments(db: Session, organization_id: str, *, now: datetime | None = None) -> list[PlatformProgramEnrollment]:
    moment = now or datetime.utcnow()
    rows = (
        db.query(PlatformProgramEnrollment)
        .filter(
            PlatformProgramEnrollment.organization_id == organization_id,
            PlatformProgramEnrollment.status.in_(ACTIVE_ENROLLMENT_STATUSES),
        )
        .all()
    )
    return [
        row
        for row in rows
        if (row.effective_at is None or row.effective_at <= moment)
        and (row.expires_at is None or row.expires_at > moment)
        and row.program in PROGRAMS
    ]


def require_active_enrollment(
    db: Session,
    organization: Organization,
    *,
    environment: str | None = None,
    operation: str | None = None,
) -> PlatformProgramEnrollment:
    if not organization_access_allowed(organization):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "organization_verification_required", "message": "The organization is not eligible for Platform API access."},
        )
    rows = active_enrollments(db, organization.id)
    if environment:
        rows = [row for row in rows if environment in set(row.allowed_environments_json or [])]
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "platform_program_enrollment_required",
                "message": "An active Platform API program enrollment is required.",
                "environment": environment,
                "operation": operation,
            },
        )
    priority = {
        "enterprise_custom": 0,
        "strategic_partner": 1,
        "developer_self_service": 2,
        "developer_private_beta": 3,
        "internal": 4,
    }
    return sorted(rows, key=lambda row: priority.get(row.program, 99))[0]


def current_api_subscription(db: Session, organization_id: str) -> PlatformApiSubscription | None:
    return (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == organization_id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )


def require_api_entitlement(
    db: Session,
    organization: Organization,
    *,
    environment: str,
    operation: str,
) -> tuple[PlatformProgramEnrollment, PlatformApiSubscription | None]:
    enrollment = require_active_enrollment(db, organization, environment=environment, operation=operation)
    if environment == "live":
        moment = datetime.utcnow()
        live_approval = (
            db.query(PlatformLiveAccessRequest)
            .filter(
                PlatformLiveAccessRequest.organization_id == organization.id,
                PlatformLiveAccessRequest.status == "approved",
            )
            .order_by(PlatformLiveAccessRequest.decided_at.desc())
            .first()
        )
        if live_approval is None or (live_approval.expires_at is not None and live_approval.expires_at <= moment):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "live_access_approval_required",
                    "message": "An active live-access approval is required for this operation.",
                },
            )
    subscription = current_api_subscription(db, organization.id)
    if enrollment.billing_mode in {"enterprise_invoice", "contract"}:
        return enrollment, subscription
    if subscription is None:
        if environment == "test" and enrollment.program in {"internal", "developer_private_beta", "strategic_partner"}:
            return enrollment, None
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "api_subscription_required", "message": "An eligible API plan is required for this operation."},
        )
    allowed = LIVE_ACCESS_SUBSCRIPTION_STATES if environment == "live" else API_ACCESS_SUBSCRIPTION_STATES
    if subscription.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "api_subscription_ineligible", "message": "The API subscription does not permit this operation."},
        )
    return enrollment, subscription


def enforce_enrollment_limit(
    db: Session,
    *,
    enrollment: PlatformProgramEnrollment,
    resource_name: str,
    current_count: int,
) -> None:
    column = {
        "projects": "maximum_projects",
        "live_projects": "maximum_live_projects",
        "service_accounts": "maximum_service_accounts",
        "keys": "maximum_keys",
        "webhooks": "maximum_webhooks",
    }.get(resource_name)
    if column is None:
        raise ValueError(f"unsupported enrollment limit: {resource_name}")
    limits = [int(getattr(enrollment, column) or 0)]
    subscription = current_api_subscription(db, enrollment.organization_id)
    if subscription is not None:
        plan = db.get(PlatformApiPlan, subscription.plan_id)
        plan_limit = (plan.limits_json or {}).get(resource_name) if plan is not None else None
        if isinstance(plan_limit, int) and not isinstance(plan_limit, bool) and plan_limit >= 0:
            limits.append(plan_limit)
    maximum = min(limits)
    if maximum >= 0 and current_count >= maximum:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "platform_resource_limit_reached",
                "resource": resource_name,
                "limit": maximum,
                "message": f"The effective Platform API entitlement permits at most {maximum} {resource_name}.",
            },
        )

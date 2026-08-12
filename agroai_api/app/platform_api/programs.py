"""Server-authoritative Platform API program and entitlement policy."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

import logging

from app.core.config import settings
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
    api_project_id: str | None,
) -> tuple[PlatformProgramEnrollment, PlatformApiSubscription | None]:
    enrollment = require_active_enrollment(db, organization, environment=environment, operation=operation)
    if environment == "live":
        moment = datetime.utcnow()
        project_scope = (
            PlatformLiveAccessRequest.api_project_id.is_(None)
            if api_project_id is None
            else or_(
                PlatformLiveAccessRequest.api_project_id.is_(None),
                PlatformLiveAccessRequest.api_project_id == api_project_id,
            )
        )
        live_approval = (
            db.query(PlatformLiveAccessRequest)
            .filter(
                PlatformLiveAccessRequest.organization_id == organization.id,
                PlatformLiveAccessRequest.status == "approved",
                project_scope,
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
        if environment == "test" and enrollment.program in {
            "internal",
            "developer_private_beta",
            "strategic_partner",
            "developer_self_service",
        }:
            # TEST development is deliberately non-billable and needs no paid
            # subscription. This branch is guarded by `environment == "test"`,
            # so LIVE always falls through to the subscription/approval checks.
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


# Server-authoritative safe limits for automatic TEST self-service enrollment.
# These are deliberately conservative and cannot be widened by client input.
SELF_SERVICE_TEST_DEFAULTS = {
    "allowed_environments": ["test"],   # TEST only — never "live"
    "maximum_projects": 3,
    "maximum_live_projects": 0,         # LIVE stays separately gated + approved
    "maximum_service_accounts": 5,
    "maximum_keys": 10,
    "maximum_webhooks": 3,
    # Advisory default scopes: read-first TEST scopes; no actions:execute
    # (physical), no connectors:sync (real provider I/O).
    "default_scopes": [
        "projects:read",
        "service_accounts:read",
        "keys:read",
        "fields:read",
        "fields:write",
        "sources:read",
        "observations:read",
        "recommendations:read",
        "reports:read",
        "jobs:read",
        "usage:read",
        "request_logs:read",
        "webhooks:read",
    ],
}

_logger = logging.getLogger("agroai.platform.self_service")


def self_service_auto_enroll_enabled() -> bool:
    return bool(getattr(settings, "PLATFORM_API_TEST_SELF_SERVICE_AUTO_ENROLL_ENABLED", False))


def ensure_self_service_test_enrollment(
    db: Session,
    organization: Organization,
    *,
    actor_user_id: str | None = None,
    now: datetime | None = None,
) -> PlatformProgramEnrollment | None:
    """Idempotently grant an eligible developer a TEST-only self-service enrollment.

    Server-authoritative. Returns the governing enrollment, or ``None`` when
    auto-enrollment is disabled, the organization is not eligible, an existing
    enrollment already governs, or a suspension must be respected. Eligibility
    of the *caller* (verified email, owner/admin membership, accepted terms) is
    enforced by ``require_developer_control_plane`` before this is invoked; this
    function additionally re-checks the server-authoritative organization state.
    """
    if not self_service_auto_enroll_enabled():
        return None
    # Re-assert the server-authoritative organization gate (never trust caller).
    if not organization_access_allowed(organization):
        return None
    moment = now or datetime.utcnow()

    # If any higher-or-equal-priority active enrollment already governs, use it.
    existing_active = active_enrollments(db, organization.id, now=moment)
    if existing_active:
        return None  # require_active_enrollment will select the governing row

    # Respect an existing developer_self_service row (e.g. a suspension is an
    # abuse control that must NOT be silently reactivated).
    existing = (
        db.query(PlatformProgramEnrollment)
        .filter(
            PlatformProgramEnrollment.organization_id == organization.id,
            PlatformProgramEnrollment.program == "developer_self_service",
        )
        .first()
    )
    if existing is not None and existing.status == "suspended":
        return None

    # Terms are a HARD prerequisite for automatic enrollment, independent of the
    # PLATFORM_API_TERMS_ENFORCEMENT_ENABLED flag: a developer is never silently
    # auto-enrolled without having accepted the CURRENT developer terms. This
    # raises (fail closed) when the current terms are unaccepted or superseded.
    from app.platform_api.terms import require_user_acceptance

    if actor_user_id is None:
        return None
    require_user_acceptance(db, organization_id=organization.id, user_id=actor_user_id)

    row = existing or PlatformProgramEnrollment(
        organization_id=organization.id,
        program="developer_self_service",
    )
    row.status = "active"
    row.allowed_environments_json = list(SELF_SERVICE_TEST_DEFAULTS["allowed_environments"])
    row.maximum_projects = SELF_SERVICE_TEST_DEFAULTS["maximum_projects"]
    row.maximum_live_projects = SELF_SERVICE_TEST_DEFAULTS["maximum_live_projects"]
    row.maximum_service_accounts = SELF_SERVICE_TEST_DEFAULTS["maximum_service_accounts"]
    row.maximum_keys = SELF_SERVICE_TEST_DEFAULTS["maximum_keys"]
    row.maximum_webhooks = SELF_SERVICE_TEST_DEFAULTS["maximum_webhooks"]
    row.default_scopes_json = list(SELF_SERVICE_TEST_DEFAULTS["default_scopes"])
    row.provider_restrictions_json = {}
    row.resource_restrictions_json = {}
    row.billing_mode = "none"
    row.support_tier = "documentation"
    row.plan_identifier = None
    row.effective_at = moment
    row.expires_at = None
    row.approved_by_user_id = None  # automatic — no human approver
    row.approved_at = moment
    row.updated_at = moment
    if existing is None:
        row.created_at = moment
        db.add(row)
    db.flush()
    # Persist the enrollment immediately: it is a distinct, idempotent grant
    # that must survive even on read-only control-plane requests (which never
    # commit the request session). This commits only the enrollment row.
    db.commit()
    _logger.info(
        "platform.self_service.auto_enrolled",
        extra={"organization_id": organization.id, "actor_user_id": actor_user_id, "program": "developer_self_service"},
    )
    return row

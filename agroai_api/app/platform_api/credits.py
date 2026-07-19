"""Atomic Platform API credit reservation and reconciliation."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import platform_quota_decisions
from app.models.platform_api import PlatformApiUsageEvent
from app.models.platform_product import (
    PlatformApiOperationCost,
    PlatformApiPlan,
    PlatformApiSubscription,
    PlatformCreditReservation,
    PlatformStripeMeterOutbox,
)
from app.models.saas import Organization
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.notifications import notify_usage_thresholds


def billing_period(subscription: PlatformApiSubscription | None, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    moment = now or datetime.utcnow()
    if (
        subscription is not None
        and subscription.current_period_start is not None
        and subscription.current_period_end is not None
        and subscription.current_period_start <= moment < subscription.current_period_end
    ):
        return (
            f"api-subscription:{subscription.current_period_start.isoformat()}:{subscription.current_period_end.isoformat()}",
            subscription.current_period_start,
            subscription.current_period_end,
        )
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return f"api-calendar:{start:%Y-%m}", start, end


def active_operation_cost(db: Session, operation_id: str, environment: str) -> int | None:
    row = (
        db.query(PlatformApiOperationCost)
        .filter(
            PlatformApiOperationCost.catalog_version == settings.PLATFORM_API_OPERATION_COST_CATALOG_VERSION,
            PlatformApiOperationCost.operation_id == operation_id,
            PlatformApiOperationCost.environment == environment,
            PlatformApiOperationCost.active.is_(True),
        )
        .first()
    )
    return int(row.credits) if row else None


def _subscription_and_plan(db: Session, organization_id: str) -> tuple[PlatformApiSubscription | None, PlatformApiPlan | None]:
    subscription = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.organization_id == organization_id,
            PlatformApiSubscription.status_slot == "active",
        )
        .first()
    )
    return subscription, db.get(PlatformApiPlan, subscription.plan_id) if subscription else None


def _scoped_logical_operation_id(operation_id: str, logical_operation_id: str) -> str:
    """Keep usage identity operation-scoped without exposing customer input."""

    return hashlib.sha256(
        f"{operation_id}\0{logical_operation_id}".encode("utf-8")
    ).hexdigest()


def reserve_credits(
    db: Session,
    *,
    principal: PlatformPrincipal,
    operation_id: str,
    logical_operation_id: str,
) -> PlatformCreditReservation | None:
    if not principal.organization_id or not principal.api_project_id or not principal.environment:
        raise HTTPException(status_code=401, detail={"code": "platform_principal_required"})
    scoped_logical_id = _scoped_logical_operation_id(operation_id, logical_operation_id)
    existing = (
        db.query(PlatformCreditReservation)
        .filter(
            PlatformCreditReservation.organization_id == principal.organization_id,
            PlatformCreditReservation.api_project_id == principal.api_project_id,
            PlatformCreditReservation.logical_operation_id == scoped_logical_id,
        )
        .first()
    )
    if existing:
        platform_quota_decisions.labels(environment=principal.environment, outcome="replay").inc()
        return existing
    credits = active_operation_cost(db, operation_id, principal.environment)
    enforcement = bool(settings.PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED)
    if credits is None:
        if enforcement:
            platform_quota_decisions.labels(environment=principal.environment, outcome="cost_missing").inc()
            raise HTTPException(status_code=503, detail={"code": "operation_cost_not_configured"})
        platform_quota_decisions.labels(environment=principal.environment, outcome="unenforced_unpriced").inc()
        return None
    organization = (
        db.query(Organization)
        .filter(Organization.id == principal.organization_id)
        .with_for_update()
        .first()
    )
    if organization is None:
        raise HTTPException(status_code=401, detail={"code": "organization_unavailable"})
    existing = (
        db.query(PlatformCreditReservation)
        .filter(
            PlatformCreditReservation.organization_id == principal.organization_id,
            PlatformCreditReservation.api_project_id == principal.api_project_id,
            PlatformCreditReservation.logical_operation_id == scoped_logical_id,
        )
        .first()
    )
    if existing:
        platform_quota_decisions.labels(environment=principal.environment, outcome="replay").inc()
        return existing
    subscription, plan = _subscription_and_plan(db, organization.id)
    period_key, period_start, period_end = billing_period(subscription)
    committed = int(
        db.query(func.coalesce(func.sum(PlatformCreditReservation.committed_credits), 0))
        .filter(
            PlatformCreditReservation.organization_id == organization.id,
            PlatformCreditReservation.billing_period_key == period_key,
            PlatformCreditReservation.state == "committed",
        )
        .scalar()
        or 0
    )
    reserved = int(
        db.query(func.coalesce(func.sum(PlatformCreditReservation.reserved_credits), 0))
        .filter(
            PlatformCreditReservation.organization_id == organization.id,
            PlatformCreditReservation.billing_period_key == period_key,
            PlatformCreditReservation.state == "reserved",
        )
        .scalar()
        or 0
    )
    included = int(plan.included_credits) if plan and plan.included_credits is not None else None
    overage = 0
    if included is not None and committed + reserved + credits > included:
        overage = committed + reserved + credits - max(included, committed + reserved)
        if not plan.overages_allowed:
            platform_quota_decisions.labels(environment=principal.environment, outcome="quota_denied").inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "api_credit_quota_exceeded", "included_credits": included},
            )
    row = PlatformCreditReservation(
        organization_id=organization.id,
        api_project_id=principal.api_project_id,
        api_key_id=principal.api_key_id,
        operation_id=operation_id,
        logical_operation_id=scoped_logical_id,
        billing_period_key=period_key,
        reserved_credits=credits,
        state="reserved",
        overage_credits=max(0, overage),
        metadata_json={"period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
    )
    db.add(row)
    db.flush()
    platform_quota_decisions.labels(
        environment=principal.environment,
        outcome="overage_reserved" if overage else "reserved",
    ).inc()
    return row


def commit_credits(
    db: Session,
    reservation: PlatformCreditReservation | None,
    *,
    principal: PlatformPrincipal,
    status_code: int,
) -> PlatformApiUsageEvent:
    logical_id = reservation.logical_operation_id if reservation else principal.request_id or str(uuid.uuid4())
    existing = (
        db.query(PlatformApiUsageEvent)
        .filter(
            PlatformApiUsageEvent.organization_id == principal.organization_id,
            PlatformApiUsageEvent.api_project_id == principal.api_project_id,
            PlatformApiUsageEvent.idempotency_key == logical_id,
        )
        .first()
    )
    if existing:
        platform_quota_decisions.labels(environment=principal.environment or "unknown", outcome="usage_replay").inc()
        return existing
    credits = int(reservation.reserved_credits) if reservation else 0
    event = PlatformApiUsageEvent(
        organization_id=principal.organization_id,
        api_project_id=principal.api_project_id,
        service_account_id=principal.service_account_id,
        api_key_id=principal.api_key_id,
        workspace_id=principal.workspace_id,
        environment=principal.environment,
        event_type="api_credit",
        metric="api_credits",
        quantity=1,
        cost_units=credits,
        operation=reservation.operation_id if reservation else "unpriced_operation",
        request_id=principal.request_id,
        idempotency_key=logical_id,
        status_code=status_code,
        metadata_json={"logical_operation_id": logical_id},
    )
    db.add(event)
    db.flush()
    platform_quota_decisions.labels(environment=principal.environment or "unknown", outcome="committed").inc()
    if reservation:
        prior_used = int(
            db.query(func.coalesce(func.sum(PlatformCreditReservation.committed_credits), 0))
            .filter(
                PlatformCreditReservation.organization_id == principal.organization_id,
                PlatformCreditReservation.billing_period_key == reservation.billing_period_key,
                PlatformCreditReservation.state == "committed",
            )
            .scalar()
            or 0
        )
        reservation.state = "committed"
        reservation.committed_credits = reservation.reserved_credits
        reservation.committed_at = datetime.utcnow()
        if reservation.overage_credits > 0:
            subscription, _plan = _subscription_and_plan(db, principal.organization_id)
            if subscription:
                identifier = hashlib.sha256(f"agroai-api-meter:{event.id}".encode()).hexdigest()
                db.add(
                    PlatformStripeMeterOutbox(
                        organization_id=principal.organization_id,
                        subscription_id=subscription.id,
                        usage_event_id=event.id,
                        meter_event_identifier=identifier,
                        meter_event_name=settings.PLATFORM_API_STRIPE_METER_EVENT_NAME or "agroai_api_credits",
                        quantity=reservation.overage_credits,
                        status="pending",
                    )
                )
        subscription, plan = _subscription_and_plan(db, principal.organization_id)
        organization = db.get(Organization, principal.organization_id)
        if settings.PLATFORM_API_BILLING_ENABLED and organization is not None and plan is not None:
            notify_usage_thresholds(
                db,
                organization=organization,
                plan=plan,
                billing_period_key=reservation.billing_period_key,
                used_credits=prior_used + credits,
                prior_used_credits=prior_used,
            )
    return event


def release_credits(db: Session, reservation: PlatformCreditReservation | None, *, reason: str) -> None:
    if reservation is None or reservation.state == "committed":
        return
    reservation.state = "released"
    reservation.released_at = datetime.utcnow()
    metadata = dict(reservation.metadata_json or {})
    metadata["release_reason"] = reason[:200]
    reservation.metadata_json = metadata
    platform_quota_decisions.labels(environment="unknown", outcome="released").inc()

"""Durable quota reservation and usage accounting for AGRO-AI."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.saas import Organization, QuotaReservation, UsageEvent
from app.services.commercial_control import get_limit


METRIC_TO_LIMIT = {
    "workspace": "quota.workspace",
    "seat": "quota.seat",
    "evidence_upload": "quota.evidence_upload.monthly",
    "ai_action": "quota.ai_action.monthly",
    "deep_investigation": "quota.deep_investigation.monthly",
    "agent_run": "quota.agent_run.monthly",
    "report_generation": "quota.report_generation.monthly",
    "report_export": "quota.report_export.monthly",
    "active_connector": "quota.active_connector",
    "managed_entity": "quota.managed_entity",
}


def current_period(org: Organization, now: datetime | None = None) -> tuple[str, datetime, datetime | None]:
    moment = now or datetime.utcnow()
    start = getattr(org, "current_period_start", None)
    end = org.current_period_end
    if start and (end is None or start <= moment < end):
        return f"subscription:{start.isoformat()}:{end.isoformat() if end else 'open'}", start, end
    month_start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = month_start.replace(year=month_start.year + 1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month + 1)
    return f"calendar:{month_start:%Y-%m}", month_start, month_end


def _metric_filter(metric: str):
    return or_(UsageEvent.metric == metric, ((UsageEvent.metric.is_(None)) & (UsageEvent.event_type == metric)))


def committed_usage(db: Session, org: Organization, metric: str, *, now: datetime | None = None) -> int:
    _period_key, period_start, period_end = current_period(org, now)
    query = db.query(func.coalesce(func.sum(UsageEvent.quantity), 0)).filter(
        UsageEvent.organization_id == org.id,
        _metric_filter(metric),
        UsageEvent.created_at >= period_start,
        or_(UsageEvent.state.is_(None), UsageEvent.state == "committed"),
    )
    if period_end is not None:
        query = query.filter(UsageEvent.created_at < period_end)
    return int(query.scalar() or 0)


def reserved_usage(db: Session, org: Organization, metric: str, *, now: datetime | None = None) -> int:
    period_key, _period_start, _period_end = current_period(org, now)
    value = (
        db.query(func.coalesce(func.sum(QuotaReservation.quantity), 0))
        .filter(
            QuotaReservation.organization_id == org.id,
            QuotaReservation.metric == metric,
            QuotaReservation.period_key == period_key,
            QuotaReservation.state == "reserved",
        )
        .scalar()
    )
    return int(value or 0)


def quota_limit(db: Session, org: Organization, metric: str) -> int | None:
    key = METRIC_TO_LIMIT.get(metric)
    return get_limit(db, org, key) if key else None


def quota_snapshot(db: Session, org: Organization, metrics: list[str] | None = None) -> dict[str, Any]:
    selected = metrics or list(METRIC_TO_LIMIT)
    period_key, period_start, period_end = current_period(org)
    rows: dict[str, Any] = {}
    for metric in selected:
        used = committed_usage(db, org, metric)
        reserved = reserved_usage(db, org, metric)
        limit = quota_limit(db, org, metric)
        remaining = None if limit is None else max(0, limit - used - reserved)
        rows[metric] = {
            "used": used,
            "reserved": reserved,
            "limit": limit,
            "remaining": remaining,
            "percent_used": None if not limit else round((used / limit) * 100, 1),
        }
    return {
        "period_key": period_key,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat() if period_end else None,
        "metrics": rows,
    }


def _reservation_for_request(
    db: Session,
    organization_id: str,
    metric: str,
    request_id: str,
) -> QuotaReservation | None:
    return (
        db.query(QuotaReservation)
        .filter(
            QuotaReservation.organization_id == organization_id,
            QuotaReservation.metric == metric,
            QuotaReservation.request_id == request_id,
        )
        .first()
    )


def reserve_quota(
    db: Session,
    org: Organization,
    metric: str,
    *,
    quantity: int = 1,
    workspace_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    unit: str = "count",
    metadata: dict[str, Any] | None = None,
) -> QuotaReservation:
    if quantity <= 0:
        raise ValueError("quota reservation quantity must be positive")

    request_key = request_id or str(uuid.uuid4())
    existing = _reservation_for_request(db, org.id, metric, request_key)
    if existing and existing.state != "released":
        return existing

    # Capacity decisions are serialized per organization. The second idempotency
    # lookup after the row lock closes the race where two concurrent requests with
    # the same request_id both miss the optimistic pre-lock lookup.
    locked_org = db.query(Organization).filter(Organization.id == org.id).with_for_update().first()
    if not locked_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    existing = _reservation_for_request(db, locked_org.id, metric, request_key)
    if existing and existing.state != "released":
        return existing

    limit = quota_limit(db, locked_org, metric)
    used = committed_usage(db, locked_org, metric)
    reserved = reserved_usage(db, locked_org, metric)
    if limit is not None and used + reserved + quantity > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "quota_exceeded",
                "metric": metric,
                "used": used,
                "reserved": reserved,
                "limit": limit,
                "message": "The current commercial quota is exhausted for this period.",
            },
        )

    period_key, _period_start, _period_end = current_period(locked_org)
    if existing:
        # A failed/released attempt may be retried with the same idempotency key.
        # Re-arm the durable row only after the serialized capacity check.
        existing.workspace_id = workspace_id
        existing.user_id = user_id
        existing.quantity = quantity
        existing.unit = unit
        existing.period_key = period_key
        existing.state = "reserved"
        existing.metadata_json = metadata or {}
        existing.committed_at = None
        existing.released_at = None
        db.flush()
        return existing

    row = QuotaReservation(
        organization_id=locked_org.id,
        workspace_id=workspace_id,
        user_id=user_id,
        metric=metric,
        quantity=quantity,
        unit=unit,
        period_key=period_key,
        request_id=request_key,
        state="reserved",
        metadata_json=metadata or {},
    )
    db.add(row)
    db.flush()
    return row


def commit_reservation(
    db: Session,
    reservation: QuotaReservation,
    *,
    event_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    existing = db.query(UsageEvent).filter(UsageEvent.reservation_id == reservation.id, UsageEvent.state == "committed").first()
    if existing:
        return existing
    if reservation.state == "released":
        raise ValueError("cannot commit a released quota reservation")

    payload = dict(reservation.metadata_json or {})
    payload.update(metadata or {})
    event = UsageEvent(
        organization_id=reservation.organization_id,
        workspace_id=reservation.workspace_id,
        user_id=reservation.user_id,
        event_type=event_type or reservation.metric,
        metric=reservation.metric,
        quantity=reservation.quantity,
        unit=reservation.unit,
        period_key=reservation.period_key,
        request_id=reservation.request_id,
        reservation_id=reservation.id,
        state="committed",
        metadata_json=payload,
    )
    reservation.state = "committed"
    reservation.committed_at = datetime.utcnow()
    db.add(event)
    db.flush()
    return event


def release_reservation(db: Session, reservation: QuotaReservation, *, reason: str | None = None) -> QuotaReservation:
    if reservation.state == "committed":
        return reservation
    reservation.state = "released"
    reservation.released_at = datetime.utcnow()
    payload = dict(reservation.metadata_json or {})
    if reason:
        payload["release_reason"] = reason
    reservation.metadata_json = payload
    db.flush()
    return reservation


def record_usage(
    db: Session,
    org: Organization,
    metric: str,
    *,
    quantity: int = 1,
    workspace_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    event_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    reservation = reserve_quota(
        db,
        org,
        metric,
        quantity=quantity,
        workspace_id=workspace_id,
        user_id=user_id,
        request_id=request_id,
        metadata=metadata,
    )
    return commit_reservation(db, reservation, event_type=event_type, metadata=metadata)

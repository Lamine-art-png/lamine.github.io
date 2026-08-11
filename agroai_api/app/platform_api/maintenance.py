"""Scheduled maintenance for Platform API billing and safe metadata retention."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.platform_product import PlatformApiPlan, PlatformApiSubscription, PlatformRequestLog
from app.platform_api.product_audit import record_product_audit


def expire_payment_grace_periods(db: Session, *, now: datetime | None = None) -> int:
    moment = now or datetime.utcnow()
    rows = (
        db.query(PlatformApiSubscription)
        .filter(
            PlatformApiSubscription.status.in_({"past_due", "grace"}),
            PlatformApiSubscription.grace_ends_at.is_not(None),
            PlatformApiSubscription.grace_ends_at <= moment,
        )
        .all()
    )
    for row in rows:
        row.status = "unpaid"
        record_product_audit(
            db,
            event_type="platform.billing.grace_expired",
            subject_type="api_subscription",
            subject_id=row.id,
            organization_id=row.organization_id,
            actor_type="system",
        )
    return len(rows)


def enforce_request_log_retention(db: Session, *, now: datetime | None = None) -> int:
    moment = now or datetime.utcnow()
    deleted = 0
    subscriptions = (
        db.query(PlatformApiSubscription)
        .filter(PlatformApiSubscription.status_slot == "active")
        .all()
    )
    for subscription in subscriptions:
        plan = db.get(PlatformApiPlan, subscription.plan_id)
        retention = (plan.limits_json or {}).get("request_log_retention_days") if plan is not None else None
        if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
            continue
        deleted += (
            db.query(PlatformRequestLog)
            .filter(
                PlatformRequestLog.organization_id == subscription.organization_id,
                PlatformRequestLog.created_at < moment - timedelta(days=retention),
            )
            .delete(synchronize_session=False)
        )
    return deleted

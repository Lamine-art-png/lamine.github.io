"""Deduplicated Platform API usage and billing notifications."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import PlatformApiKey
from app.models.platform_product import PlatformApiPlan, PlatformNotification
from app.models.saas import Organization, User
from app.platform_api.product_audit import record_product_audit
from app.platform_api.product_emails import queue_and_send_product_email


def _owner(db: Session, organization: Organization) -> User | None:
    return db.get(User, organization.owner_user_id) if organization.owner_user_id else None


def notify_usage_thresholds(
    db: Session,
    *,
    organization: Organization,
    plan: PlatformApiPlan,
    billing_period_key: str,
    used_credits: int,
    prior_used_credits: int,
) -> None:
    included = int(plan.included_credits or 0)
    owner = _owner(db, organization)
    if included <= 0 or owner is None:
        return
    thresholds = sorted(
        {
            int(value)
            for value in str(settings.PLATFORM_API_USAGE_NOTIFICATION_THRESHOLDS).split(",")
            if value.strip().isdigit() and 1 <= int(value) <= 100
        }
    )
    for threshold in thresholds:
        crossed = prior_used_credits * 100 < included * threshold <= used_credits * 100
        if not crossed:
            continue
        notification_type = f"usage_{threshold}"
        if notification_type not in {"usage_50", "usage_80", "usage_100"}:
            continue
        queue_and_send_product_email(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            to_email=owner.email,
            notification_type=notification_type,
            dedupe_key=f"{billing_period_key}:{notification_type}",
            safe_context={"billing_period": billing_period_key, "plan": plan.plan_identifier},
        )
    if prior_used_credits <= included < used_credits and plan.overages_allowed:
        queue_and_send_product_email(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            to_email=owner.email,
            notification_type="overage_started",
            dedupe_key=f"{billing_period_key}:overage_started",
            safe_context={"billing_period": billing_period_key, "plan": plan.plan_identifier},
        )


def notify_subscription_state(
    db: Session,
    *,
    organization: Organization,
    subscription_id: str,
    notification_type: str,
    event_id: str,
) -> None:
    owner = _owner(db, organization)
    if owner is None:
        return
    queue_and_send_product_email(
        db,
        organization_id=organization.id,
        user_id=owner.id,
        to_email=owner.email,
        notification_type=notification_type,
        dedupe_key=f"api-subscription:{subscription_id}:{event_id}:{notification_type}",
    )
    record_product_audit(
        db,
        event_type=f"platform.notification.{notification_type}",
        subject_type="api_subscription",
        subject_id=subscription_id,
        organization_id=organization.id,
        actor_type="system",
    )


def process_key_expiration_notifications(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Notify organization owners once per key expiration timestamp."""

    moment = now or datetime.utcnow()
    cutoff = moment + timedelta(days=max(1, int(settings.PLATFORM_API_KEY_EXPIRY_NOTIFICATION_DAYS)))
    rows = (
        db.query(PlatformApiKey)
        .filter(
            PlatformApiKey.status == "active",
            PlatformApiKey.expires_at.is_not(None),
            PlatformApiKey.expires_at > moment,
            PlatformApiKey.expires_at <= cutoff,
        )
        .all()
    )
    created = 0
    for key in rows:
        organization = db.get(Organization, key.organization_id)
        owner = _owner(db, organization) if organization is not None else None
        if owner is None:
            continue
        before = db.query(PlatformNotification).filter_by(
            organization_id=organization.id,
            notification_type="key_nearing_expiration",
            dedupe_key=f"api-key:{key.id}:expires:{key.expires_at.isoformat()}",
        ).count()
        queue_and_send_product_email(
            db,
            organization_id=organization.id,
            user_id=owner.id,
            to_email=owner.email,
            notification_type="key_nearing_expiration",
            dedupe_key=f"api-key:{key.id}:expires:{key.expires_at.isoformat()}",
            safe_context={"key_fingerprint": key.fingerprint, "expires_at": key.expires_at.isoformat()},
        )
        created += int(before == 0)
    return {"eligible": len(rows), "created": created}

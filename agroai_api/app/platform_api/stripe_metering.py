"""Durable Queue-backed Stripe Billing Meter export."""
from __future__ import annotations

from datetime import datetime, timedelta

import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import platform_billing_events
from app.db.base import SessionLocal
from app.models.platform_product import PlatformApiSubscription, PlatformStripeMeterOutbox
from app.platform_api.stripe_mode import platform_stripe_livemode_matches
from app.services.redis_task_queue import get_task_publisher


STRIPE_METER_TASK_TYPE = "platform_stripe_meter_export"


def stripe_api_ready() -> bool:
    return bool(
        settings.PLATFORM_API_STRIPE_SECRET_KEY
        and settings.PLATFORM_API_STRIPE_METER_EVENT_NAME
        and settings.PLATFORM_API_STRIPE_METER_ID
    )


def publish_pending_meter_outbox(db: Session, *, limit: int = 100) -> dict[str, int]:
    if not settings.PLATFORM_API_STRIPE_METER_EXPORT_ENABLED:
        return {"published": 0, "failed": 0}
    now = datetime.utcnow()
    stale_claim = now - timedelta(minutes=10)
    rows = (
        db.query(PlatformStripeMeterOutbox)
        .filter(
            (PlatformStripeMeterOutbox.status == "pending")
            | (
                (PlatformStripeMeterOutbox.status == "publishing")
                & (
                    (PlatformStripeMeterOutbox.claimed_at.is_(None))
                    | (PlatformStripeMeterOutbox.claimed_at <= stale_claim)
                )
            ),
            (PlatformStripeMeterOutbox.next_attempt_at.is_(None)) | (PlatformStripeMeterOutbox.next_attempt_at <= now),
        )
        .order_by(PlatformStripeMeterOutbox.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 200)))
        .all()
    )
    if not rows:
        return {"published": 0, "failed": 0}
    publisher = get_task_publisher()
    published = failed = 0
    for row in rows:
        row.status = "publishing"
        row.claimed_at = now
        db.commit()
        try:
            publisher.enqueue(row.id, row.organization_id, STRIPE_METER_TASK_TYPE)
            row.status = "queued"
            row.last_error_class = None
            published += 1
        except Exception as exc:
            row.status = "pending"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(3600, 2 ** min(row.attempt_count, 10)))
            row.last_error_class = exc.__class__.__name__
            failed += 1
        db.commit()
    return {"published": published, "failed": failed}


def process_meter_export_task(*, outbox_id: str, organization_id: str, worker_id: str) -> str:
    del worker_id
    if not settings.PLATFORM_API_STRIPE_METER_EXPORT_ENABLED:
        return "disabled"
    db = SessionLocal()
    try:
        row = (
            db.query(PlatformStripeMeterOutbox)
            .filter(
                PlatformStripeMeterOutbox.id == outbox_id,
                PlatformStripeMeterOutbox.organization_id == organization_id,
            )
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None or row.status in {"exported", "reconciled", "failed"}:
            platform_billing_events.labels(event_class="meter_export", outcome="idempotent_terminal").inc()
            return "succeeded" if row is None else row.status
        subscription = db.get(PlatformApiSubscription, row.subscription_id)
        if subscription is None or subscription.organization_id != organization_id or not subscription.stripe_customer_id:
            row.status = "failed"
            row.last_error_class = "stripe_customer_mapping_missing"
            db.commit()
            platform_billing_events.labels(event_class="meter_export", outcome="mapping_failed").inc()
            return "failed"
        if not stripe_api_ready():
            row.status = "pending"
            row.next_attempt_at = datetime.utcnow() + timedelta(minutes=5)
            row.last_error_class = "stripe_meter_not_configured"
            db.commit()
            platform_billing_events.labels(event_class="meter_export", outcome="not_configured").inc()
            return "retrying"
        row.status = "exporting"
        row.attempt_count = int(row.attempt_count or 0) + 1
        db.commit()
        stripe.api_key = settings.PLATFORM_API_STRIPE_SECRET_KEY
        try:
            meter_event = stripe.billing.MeterEvent.create(
                event_name=row.meter_event_name,
                payload={
                    "stripe_customer_id": subscription.stripe_customer_id,
                    "value": str(row.quantity),
                },
                identifier=row.meter_event_identifier[:100],
            )
            if not platform_stripe_livemode_matches(
                mode=settings.PLATFORM_API_STRIPE_MODE,
                livemode=bool(getattr(meter_event, "livemode", False)),
            ):
                raise RuntimeError("stripe_meter_mode_mismatch")
            row.status = "exported"
            row.exported_at = datetime.utcnow()
            row.next_attempt_at = None
            row.last_error_class = None
            db.commit()
            platform_billing_events.labels(event_class="meter_export", outcome="exported").inc()
            return "succeeded"
        except Exception as exc:
            db.rollback()
            row = db.get(PlatformStripeMeterOutbox, outbox_id)
            attempts = int(row.attempt_count or 0)
            terminal = attempts >= int(settings.PLATFORM_API_METER_EXPORT_MAX_ATTEMPTS)
            row.status = "failed" if terminal else "pending"
            row.next_attempt_at = None if terminal else datetime.utcnow() + timedelta(seconds=min(3600, 2 ** min(attempts, 10)))
            row.last_error_class = exc.__class__.__name__
            db.commit()
            platform_billing_events.labels(
                event_class="meter_export",
                outcome="terminal_failed" if terminal else "retrying",
            ).inc()
            return "failed" if terminal else "retrying"
    finally:
        db.close()

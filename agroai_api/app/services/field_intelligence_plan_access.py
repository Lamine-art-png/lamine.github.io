"""Field Intelligence launch packaging and durable monthly record metering.

A Field Intelligence record is consumed only when a new capture is completed
into an observation. Initiation, media upload, idempotent completion replay,
transcript correction and reprocessing do not consume another record.

The two-record Free experience includes model-assisted extraction in production.
Development and test environments keep the earlier deterministic default unless
they explicitly opt into production mode, which preserves deliberate test and
local-development controls while making the public launch behavior authoritative.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, status

PLAN_RECORD_LIMITS: dict[str, int | None] = {
    "free": 2,
    "professional": 100,
    "team": 500,
    "network": 2500,
    "enterprise": None,
}
NEXT_PLAN: dict[str, str] = {
    "free": "professional",
    "professional": "team",
    "team": "network",
    "network": "enterprise",
}
RECORD_METRIC = "field_record"
ENTITLEMENT_KEY = "quota.field_intelligence.records.monthly"
MODEL_EXTRACTION_KEY = "field_intelligence.model_extraction"


def _plan_id(value: str | None) -> str:
    from app.services.product_plans import plan_by_id

    return str(plan_by_id(value)["id"])


def _quota_error(exc: HTTPException, plan: str) -> HTTPException:
    detail = dict(exc.detail) if isinstance(exc.detail, dict) else {}
    detail.update(
        {
            "code": "quota_exceeded",
            "metric": "field_intelligence.records.monthly",
            "recommended_plan": NEXT_PLAN.get(plan),
            "message": "The monthly Field Intelligence record allowance for this plan is used up.",
        }
    )
    if detail.get("recommended_plan") is None:
        detail.pop("recommended_plan", None)
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def _meter_complete_capture(original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(db, ctx, capture_ref: str, payload: dict | None = None):
        from app.models.field_intelligence import FieldObservation
        from app.services import field_intelligence as svc
        from app.services.commercial_control import resolve_effective_entitlements
        from app.services.quota import record_usage

        organization_id = svc.require_org(ctx)
        session = svc._load_session(db, organization_id, capture_ref)

        # Completion is idempotent. A retry of a record already created must not
        # consume quota, even when the plan has since reached its limit.
        if session.observation_id:
            observation = db.get(FieldObservation, session.observation_id)
            if observation is not None:
                return original(db, ctx, capture_ref, payload)
        existing = (
            db.query(FieldObservation)
            .filter(FieldObservation.capture_session_id == session.id)
            .first()
        )
        if existing is not None:
            return original(db, ctx, capture_ref, payload)

        effective = resolve_effective_entitlements(db, ctx.organization)
        source = str(effective.sources.get(ENTITLEMENT_KEY, ""))
        quota_plan = "free" if source.startswith("subscription:") else _plan_id(effective.plan)
        try:
            record_usage(
                db,
                ctx.organization,
                RECORD_METRIC,
                quantity=1,
                workspace_id=session.workspace_id,
                user_id=ctx.user.id,
                request_id=f"field-record:{session.id}",
                event_type="field_intelligence_record_completed",
                metadata={"surface": "field_intelligence", "capture_session_id": session.id},
            )
            return original(db, ctx, capture_ref, payload)
        except HTTPException as exc:
            db.rollback()
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                raise _quota_error(exc, quota_plan) from exc
            raise
        except Exception:
            db.rollback()
            raise

    wrapped.__name__ = getattr(original, "__name__", "complete_capture")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    wrapped.__agroai_field_record_metered__ = True
    return wrapped


def _production_free_model_resolver(original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(db, org, *, at_time=None):
        from app.core.config import settings
        from app.services import commercial_control

        effective = original(db, org, at_time=at_time)
        if str(settings.APP_ENV or "").strip().lower() != "production":
            return effective

        inactive_paid = (
            effective.plan != "free"
            and effective.subscription_status not in commercial_control.ACTIVE_PAID_STATES
        )
        if effective.plan != "free" and not inactive_paid:
            return effective

        source = str(effective.sources.get(MODEL_EXTRACTION_KEY, ""))
        # Contract and organization overrides remain authoritative. The launch
        # default only upgrades plan/subscription-derived Free-equivalent access.
        if source and not (source.startswith("plan:") or source.startswith("subscription:")):
            return effective

        values = dict(effective.values)
        sources = dict(effective.sources)
        values[MODEL_EXTRACTION_KEY] = "enabled"
        sources[MODEL_EXTRACTION_KEY] = "launch:free-two-record"
        return commercial_control.EffectiveEntitlements(
            organization_id=effective.organization_id,
            plan=effective.plan,
            plan_version=effective.plan_version,
            customer_class=effective.customer_class,
            organization_type=effective.organization_type,
            subscription_status=effective.subscription_status,
            values=values,
            sources=sources,
        )

    wrapped.__name__ = getattr(original, "__name__", "resolve_effective_entitlements")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    wrapped.__agroai_field_record_access__ = True
    return wrapped


def install_field_intelligence_plan_access() -> None:
    """Install canonical plan limits, metering, and the production Free launch.

    Plan defaults are written before the canonical resolver applies commercial
    contracts and organization overrides. Inactive paid subscriptions therefore
    inherit Free's two-record allowance through the existing restriction layer,
    while Enterprise contract capacity remains authoritative.
    """
    from app.services import commercial_control, field_intelligence, quota

    # Reapply these declarations on every installer call. Tests and worker
    # bootstraps may restore module dictionaries without restarting the process.
    for plan, limit in PLAN_RECORD_LIMITS.items():
        commercial_control.BASE_ENTITLEMENTS[plan][ENTITLEMENT_KEY] = limit
    quota.METRIC_TO_LIMIT[RECORD_METRIC] = ENTITLEMENT_KEY

    current_resolver = commercial_control.resolve_effective_entitlements
    if not getattr(current_resolver, "__agroai_field_record_access__", False):
        commercial_control.resolve_effective_entitlements = _production_free_model_resolver(current_resolver)

    current_complete = field_intelligence.complete_capture
    if not getattr(current_complete, "__agroai_field_record_metered__", False):
        field_intelligence.complete_capture = _meter_complete_capture(current_complete)

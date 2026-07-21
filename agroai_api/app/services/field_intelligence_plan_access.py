"""Field Intelligence launch packaging and durable monthly record metering.

A Field Intelligence record is consumed only when a new capture is completed
into an observation. Initiation, media upload, idempotent completion replay,
transcript correction and reprocessing do not consume another record.
"""
from __future__ import annotations

from dataclasses import replace
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
_INSTALLED = False


def _plan_id(value: str | None) -> str:
    from app.services.product_plans import plan_by_id

    return str(plan_by_id(value)["id"])


def _enrich_effective_entitlements(original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(db, org, *, at_time=None):
        effective = original(db, org, at_time=at_time)
        values = dict(effective.values)
        sources = dict(effective.sources)
        limit = PLAN_RECORD_LIMITS.get(effective.plan)
        values[ENTITLEMENT_KEY] = limit
        sources[ENTITLEMENT_KEY] = f"field_intelligence_launch:{effective.plan}"

        # Free is a real two-record product experience. Model-assisted
        # extraction is affordable because record throughput is tightly bounded.
        if effective.plan == "free":
            values["field_intelligence.model_extraction"] = "enabled"
            sources["field_intelligence.model_extraction"] = "field_intelligence_launch:free"

        return replace(effective, values=values, sources=sources)

    wrapped.__name__ = getattr(original, "__name__", "resolve_effective_entitlements")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    return wrapped


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

        plan = _plan_id(getattr(ctx.organization, "plan", None))
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
                raise _quota_error(exc, plan) from exc
            raise
        except Exception:
            db.rollback()
            raise

    wrapped.__name__ = getattr(original, "__name__", "complete_capture")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    return wrapped


def install_field_intelligence_plan_access() -> None:
    """Install once during API assembly, before Field Intelligence requests run."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import commercial_control, field_intelligence, quota

    commercial_control.resolve_effective_entitlements = _enrich_effective_entitlements(
        commercial_control.resolve_effective_entitlements
    )
    quota.METRIC_TO_LIMIT[RECORD_METRIC] = ENTITLEMENT_KEY
    field_intelligence.complete_capture = _meter_complete_capture(field_intelligence.complete_capture)
    _INSTALLED = True

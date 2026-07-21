"""Field Intelligence launch packaging and durable monthly record metering.

A Field Intelligence record is consumed only when a new capture is completed
into an observation. Initiation, media upload, idempotent completion replay,
transcript correction and reprocessing do not consume another record.
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
_INSTALLED = False


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
    wrapped.__agroai_field_record_metered__ = True
    return wrapped


def install_field_intelligence_plan_access() -> None:
    """Install once during API assembly, before Field Intelligence requests run.

    Plan values are written into the canonical BASE_ENTITLEMENTS dictionaries,
    rather than layered through another resolver wrapper. This keeps the policy
    stable when other startup hardeners are re-installed during tests or worker
    bootstrap and makes inactive paid plans correctly fall back to Free's two-
    record allowance.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import commercial_control, field_intelligence, quota

    for plan, limit in PLAN_RECORD_LIMITS.items():
        commercial_control.BASE_ENTITLEMENTS[plan][ENTITLEMENT_KEY] = limit

    # Free is a real two-record product experience. Model-assisted extraction is
    # affordable because throughput is tightly bounded at the organization level.
    commercial_control.BASE_ENTITLEMENTS["free"]["field_intelligence.model_extraction"] = "enabled"

    quota.METRIC_TO_LIMIT[RECORD_METRIC] = ENTITLEMENT_KEY
    current_complete = field_intelligence.complete_capture
    if not getattr(current_complete, "__agroai_field_record_metered__", False):
        field_intelligence.complete_capture = _meter_complete_capture(current_complete)
    _INSTALLED = True

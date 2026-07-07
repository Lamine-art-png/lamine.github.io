"""Customer-facing monetization convergence endpoints.

This module keeps the portal on one commercial source of truth:
- period-aware durable quota snapshots
- effective entitlements resolved from the canonical control plane
- one checkout bridge that delegates to the authoritative Stripe checkout endpoint
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1 import billing as billing_api
from app.db.base import get_db
from app.services.entitlements import require_owner_or_admin, serialize_entitlements
from app.services.product_plans import plan_by_id, service_add_ons, upgrade_options
from app.services.quota import quota_snapshot

router = APIRouter(tags=["monetization-convergence"])


class AuthoritativeCheckoutRequest(BaseModel):
    plan_id: Literal["free", "professional", "team", "network", "enterprise"]
    billing_period: Literal["monthly", "annual"] = "monthly"


def _require_org(ctx: AuthContext):
    if not ctx.organization or not ctx.membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization, ctx.membership


def _offer(plan_id: str, billing_period: str) -> str:
    return f"{plan_id}_{billing_period}"


def _quota_rows(snapshot: dict) -> list[dict]:
    labels = {
        "workspace": "Workspaces",
        "seat": "Seats",
        "evidence_upload": "Evidence uploads",
        "ai_action": "AGRO-AI actions",
        "deep_investigation": "Deep investigations",
        "agent_run": "Agent runs",
        "report_generation": "Report generations",
        "report_export": "Report exports",
        "active_connector": "Active connectors",
        "managed_entity": "Managed entities",
    }
    upgrade_targets = {
        "workspace": "professional",
        "seat": "team",
        "evidence_upload": "professional",
        "ai_action": "professional",
        "deep_investigation": "professional",
        "agent_run": "professional",
        "report_generation": "professional",
        "report_export": "professional",
        "active_connector": "professional",
        "managed_entity": "network",
    }
    rows: list[dict] = []
    for metric, value in (snapshot.get("metrics") or {}).items():
        row = dict(value or {})
        row.update(
            {
                "metric": metric,
                "label": labels.get(metric, metric.replace("_", " ").title()),
                "recommended_plan": upgrade_targets.get(metric, "professional"),
            }
        )
        rows.append(row)
    return rows


@router.get("/billing/commercial-summary")
def commercial_summary(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict:
    org, membership = _require_org(ctx)
    snapshot = quota_snapshot(db, org)
    current_plan = plan_by_id(org.plan)
    return {
        "current_plan": current_plan,
        "plan_id": current_plan["id"],
        "billing_status": org.subscription_status or "inactive",
        "subscription_source": getattr(org, "subscription_source", None) or "local",
        "current_period_start": snapshot.get("period_start"),
        "current_period_end": snapshot.get("period_end"),
        "cancel_at_period_end": bool(getattr(org, "cancel_at_period_end", False)),
        "quota_snapshot": snapshot,
        "quota_rows": _quota_rows(snapshot),
        "entitlements": serialize_entitlements(org, db),
        "upgrade_options": upgrade_options(org.plan),
        "service_add_ons": service_add_ons(),
        "can_manage_billing": membership.role in {"owner", "admin"},
    }


@router.post("/billing/checkout-authoritative")
def checkout_authoritative(
    payload: AuthoritativeCheckoutRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    org, membership = _require_org(ctx)
    require_owner_or_admin(membership.role)

    selected = plan_by_id(payload.plan_id)
    if selected["id"] == "free":
        return {"status": "available", "message": "Free workspace is already available.", "plan": selected}
    if selected["id"] == "enterprise":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "sales_required",
                "message": "Enterprise plans require a scoped commercial rollout.",
                "recommended_plan": "enterprise",
            },
        )

    checkout_payload = billing_api.CheckoutRequest(
        organization_id=org.id,
        offer=_offer(selected["id"], payload.billing_period),
    )
    result = billing_api.create_checkout_session(checkout_payload, user=ctx.user, db=db)
    return {**result, "status": "checkout_ready", "plan": selected, "billing_period": payload.billing_period}

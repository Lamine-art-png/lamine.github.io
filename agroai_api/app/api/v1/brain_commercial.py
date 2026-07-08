"""Commercially differentiated Ask AGRO-AI reasoning modes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.brain import BrainRunRequest
from app.api.v1.brain_safety import brain_run_safe
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, User
from app.services.commercial_control import canonical_plan, require_feature
from app.services.quota import commit_reservation, release_reservation, reserve_quota

router = APIRouter(tags=["intelligence-commercial"])


def _organization(db: Session, tenant_id: str) -> Organization:
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise ValueError("Organization not found")
    return org


@router.post("/run-commercial")
async def brain_run_commercial(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run Ask AGRO-AI with an additional meter for expensive Deep reasoning.

    Every request still consumes the canonical ``ai_action`` quota inside
    ``brain_run``. Deep requests additionally consume ``deep_investigation``.
    Free gets a deliberately small two-run preview from its existing quota;
    paid plans require the Deep entitlement and receive larger plan capacity.
    """
    org = _organization(db, tenant_id)
    is_deep = payload.task == "deep_analysis"
    deep_reservation = None

    if is_deep:
        plan = canonical_plan(org.plan)
        if plan != "free":
            require_feature(
                db,
                org,
                "intelligence.deep_analysis",
                recommended_plan="professional",
            )
        deep_reservation = reserve_quota(
            db,
            org,
            "deep_investigation",
            workspace_id=payload.workspace_id,
            user_id=user.id,
            metadata={"task": payload.task, "surface": "ask_agro_ai"},
        )

    try:
        response = await brain_run_safe(
            payload=payload,
            tenant_id=tenant_id,
            user=user,
            db=db,
        )
        if deep_reservation is not None:
            if response.get("status") == "completed":
                commit_reservation(
                    db,
                    deep_reservation,
                    event_type="deep_analysis",
                    metadata={"surface": "ask_agro_ai", "status": "completed"},
                )
            else:
                release_reservation(db, deep_reservation, reason="deep_analysis_not_completed")
            db.commit()
        response["reasoning_mode"] = "deep" if is_deep else "standard"
        return response
    except Exception:
        if deep_reservation is not None:
            release_reservation(db, deep_reservation, reason="deep_analysis_exception")
            db.commit()
        raise

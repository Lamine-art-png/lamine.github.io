"""Authoritative paid boundary for Ask AGRO-AI inference routes.

The customer-facing portal has several rolling-deploy and recovery routes for
Ask AGRO-AI. This router is included ahead of those compatibility routes so a
Free account cannot bypass the commercial boundary by calling an older or
fallback endpoint directly.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1 import ai_stable, brain, brain_commercial, brain_safety, platform_intelligence
from app.api.v1.brain import BrainRunRequest
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, User
from app.schemas.ai import ChatRequest, IntelligenceRunRequest
from app.services.ask_agro_ai_commercial_policy import install_ask_agro_ai_commercial_policy
from app.services.commercial_control import require_feature


router = APIRouter(tags=["ask-agro-ai-commercial"])
install_ask_agro_ai_commercial_policy()


def _require_paid_ask(db: Session, tenant_id: str) -> Organization:
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    require_feature(
        db,
        org,
        "intelligence.ask",
        recommended_plan="professional",
    )
    return org


@router.post("/runtime/intelligence-run", include_in_schema=False)
async def paid_resilient_intelligence_run(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_paid_ask(db, tenant_id)
    return await ai_stable.resilient_intelligence_run(
        payload=payload,
        tenant_id=tenant_id,
        user=user,
        db=db,
    )


@router.post("/intelligence/brain/run", include_in_schema=False)
async def paid_brain_run(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_paid_ask(db, tenant_id)
    return await brain.brain_run(payload=payload, tenant_id=tenant_id, user=user, db=db)


@router.post("/intelligence/brain/run-safe", include_in_schema=False)
async def paid_brain_run_safe(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_paid_ask(db, tenant_id)
    return await brain_safety.brain_run_safe(payload=payload, tenant_id=tenant_id, user=user, db=db)


@router.post("/intelligence/brain/run-commercial", include_in_schema=False)
async def paid_brain_run_commercial(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_paid_ask(db, tenant_id)
    return await brain_commercial.brain_run_commercial(payload=payload, tenant_id=tenant_id, user=user, db=db)


@router.post("/intelligence/run", include_in_schema=False)
async def paid_legacy_intelligence_run(
    payload: IntelligenceRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_paid_ask(db, tenant_id)
    return await platform_intelligence.intelligence_run(
        payload=payload,
        tenant_id=tenant_id,
        user=user,
        db=db,
    )


@router.post("/ai/chat", include_in_schema=False)
async def paid_legacy_ai_chat(
    payload: ChatRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
):
    _require_paid_ask(db, tenant_id)
    return await ai_stable.chat(payload=payload, tenant_id=tenant_id, db=db)

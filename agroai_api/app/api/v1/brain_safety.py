from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.brain import BrainRunRequest, brain_run
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.services.decision_safety import evaluate_decision_safety
from app.services.intelligence_context import build_intelligence_context


router = APIRouter(tags=["intelligence-safety"])


@router.post("/run-safe")
async def brain_run_safe(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    response = await brain_run(payload=payload, tenant_id=tenant_id, user=user, db=db)
    if response.get("status") != "completed":
        return response

    result = response.get("result") or {}
    answer = str(result.get("answer") or result.get("summary") or "")
    bundle = build_intelligence_context(
        db=db,
        tenant_id=tenant_id,
        user=user,
        workspace_id=payload.workspace_id,
        field_id=payload.field_id,
        audience=payload.audience,
    )
    context = bundle["evidence_context"]
    envelope = evaluate_decision_safety(
        task=payload.task,
        question=payload.question,
        answer=answer,
        context=context,
        sample_mode=bool(bundle.get("sample_mode")),
    )
    safety = envelope.to_dict()

    result["decision_safety"] = safety
    result["execution_allowed"] = False
    if envelope.status == "blocked":
        result["confidence"] = "low"
        result["recommendations"] = []
        result["operator_instructions"] = []
        result["next_actions"] = []
    elif envelope.status == "approval_required":
        result["approval_required"] = True

    response["result"] = result
    response["decision_safety"] = safety
    response["decision_status"] = envelope.status
    response["execution_allowed"] = False
    if envelope.status == "blocked":
        response["confidence"] = "low"
    return response

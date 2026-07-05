from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.brain import BrainRunRequest, brain_run
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.hardened_records import IntelligenceRunProvenanceState
from app.models.operational_records import IntelligenceRun
from app.models.saas import User
from app.services.claim_provenance import build_claim_provenance
from app.services.decision_safety import evaluate_decision_safety
from app.services.intelligence_context import build_intelligence_context


router = APIRouter(tags=["intelligence-safety"])


def _persist_safe_run(
    db: Session,
    *,
    tenant_id: str,
    user: User,
    payload: BrainRunRequest,
    response: dict[str, Any],
    provenance: dict[str, Any],
) -> str | None:
    try:
        citations = list(response.get("citations") or [])
        run = IntelligenceRun(
            tenant_id=tenant_id,
            workspace_id=payload.workspace_id,
            user_id=user.id,
            run_type=payload.task,
            question=payload.question,
            input_context_json={
                "field_id": payload.field_id,
                "audience": payload.audience,
                "preferred_language": payload.preferred_language,
                "history_items": len(payload.history),
                "uploaded_evidence_items": len(payload.uploaded_evidence),
            },
            output_json=response.get("result") or {},
            citations_json=citations,
            model_provider=response.get("provider"),
            model_name=response.get("selected_model"),
            status="completed",
        )
        db.add(run)
        db.flush()
        state = db.get(IntelligenceRunProvenanceState, run.id)
        if state is not None:
            state.provenance_json = {"claims": provenance.get("claims", []), "unsupported_consequential_count": provenance.get("unsupported_consequential_count", 0), "stale_operational_count": provenance.get("stale_operational_count", 0)}
            state.freshness_json = provenance.get("freshness") or {}
        db.commit()
        return run.id
    except Exception:
        db.rollback()
        return None


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
    provenance = build_claim_provenance(task=payload.task, answer=answer, context=context)
    safety = envelope.to_dict()

    provenance_block = bool(provenance.get("unsupported_consequential_count"))
    freshness_block = bool((provenance.get("freshness") or {}).get("blocking_count")) and envelope.operational_intent
    effective_status = envelope.status
    extra_reasons: list[str] = []
    if provenance_block and envelope.operational_intent:
        effective_status = "blocked"
        extra_reasons.append("one or more consequential claims lack concrete record-level support")
    if freshness_block:
        effective_status = "blocked"
        extra_reasons.append("stale or timestamp-unknown evidence cannot authorize the current operating decision")
    safety["status"] = effective_status
    safety["execution_candidate"] = effective_status == "approval_required"
    safety["approval_required"] = effective_status == "approval_required"
    safety["reasons"] = list(dict.fromkeys(list(safety.get("reasons") or []) + extra_reasons))

    result["decision_safety"] = safety
    result["claim_provenance"] = provenance.get("claims", [])
    result["evidence_freshness"] = provenance.get("freshness") or {}
    result["execution_allowed"] = False
    if effective_status == "blocked":
        result["confidence"] = "low"
        result["recommendations"] = []
        result["operator_instructions"] = []
        result["next_actions"] = []
        result["approval_required"] = False
    elif effective_status == "approval_required":
        result["approval_required"] = True

    response["result"] = result
    response["decision_safety"] = safety
    response["decision_status"] = effective_status
    response["claim_provenance"] = provenance.get("claims", [])
    response["evidence_freshness"] = provenance.get("freshness") or {}
    response["execution_allowed"] = False
    if effective_status == "blocked":
        response["confidence"] = "low"

    run_id = _persist_safe_run(db, tenant_id=tenant_id, user=user, payload=payload, response=response, provenance=provenance)
    if run_id:
        response["intelligence_run_id"] = run_id
        result["intelligence_run_id"] = run_id
    return response

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.ai import _deterministic_body, _get_evidence_context, _verification
from app.api.v1.brain import (
    BrainRunRequest,
    attach_uploaded_evidence,
    compact_local_messages,
    language_failure_response,
    local_plain_body,
)
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Organization, User
from app.schemas.ai import ChatRequest, ChatResponse
from app.services.ai_gateway import parse_model_json
from app.services.intelligence_context import build_intelligence_context
from app.services.language import language_matches_target, resolve_language
from app.services.model_router import ModelRouter
from app.services.quota import commit_reservation, release_reservation, reserve_quota
from app.services.resilient_intelligence import run_resilient_intelligence

router = APIRouter(tags=["ai-stable"])


SYSTEM = """You are AGRO-AI, the agriculture operations intelligence layer.
Return customer-safe JSON only using this shape:
{"summary":"...","answer":"...","work_completed":[],"available_data":[],"missing_data":[],"recommendations":[],"next_actions":[],"risk_flags":[],"confidence":"low|medium|high","customer_safe":true}
Never invent live telemetry, integrations, water use, compliance status, yield, savings, or customer facts. Use only supplied context. Do not expose runtime/provider/debug details."""


def _normalize(body: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        return fallback
    summary = str(body.get("summary") or body.get("answer") or "").strip()
    if not summary or summary.lower().startswith("reasoning-only") or "<think>" in summary.lower():
        return fallback
    merged = {**fallback, **body}
    merged["summary"] = summary
    merged["answer"] = str(merged.get("answer") or summary)
    merged["customer_safe"] = True
    return merged


@router.get("/runtime/ai-router-status")
async def ai_router_status() -> dict[str, Any]:
    """Public, secret-free inference-lane diagnostics for production verification."""
    status = ModelRouter().status()
    return {
        "status": "ok",
        "configured": status.get("configured"),
        "provider": status.get("provider"),
        "mode": status.get("mode"),
        "routing_mode": status.get("routing_mode"),
        "fallback_active": status.get("fallback_active"),
        "missing_env": status.get("missing_env", []),
        "test_commands_enabled": status.get("test_commands_enabled"),
        "lanes": status.get("lanes", {}),
        "profiles": status.get("profiles", {}),
    }


@router.post("/runtime/intelligence-run")
async def resilient_intelligence_run(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Production recovery route with independent edge/free-hosted fallbacks."""
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise ValueError("Organization not found")

    bundle = build_intelligence_context(
        db=db,
        tenant_id=tenant_id,
        user=user,
        workspace_id=payload.workspace_id,
        field_id=payload.field_id,
        audience=payload.audience,
    )
    context = bundle["evidence_context"]
    attach_uploaded_evidence(context, payload.uploaded_evidence)
    messages = compact_local_messages(
        question=payload.question,
        context=context,
        history=payload.history,
        audience=payload.audience,
        uploaded_evidence=payload.uploaded_evidence,
        preferred_language=payload.preferred_language,
    )
    commercial = bundle.get("commercial_intelligence") or {}
    reservation = reserve_quota(
        db,
        org,
        "ai_action",
        workspace_id=payload.workspace_id,
        user_id=user.id,
        metadata={"task": payload.task, "route": "resilient_runtime"},
    )
    try:
        result = await run_resilient_intelligence(
            task=payload.task,
            question=payload.question,
            messages=messages,
            preferred_language=payload.preferred_language,
        )
        commit_reservation(
            db,
            reservation,
            event_type="ai_run",
            metadata={
                "status": result.status,
                "task_profile": result.profile,
                "provider_internal": result.provider,
                "model_internal": result.model,
                "route": "resilient_runtime",
            },
        )
        db.commit()
    except Exception:
        release_reservation(db, reservation, reason="resilient_runtime_exception")
        db.commit()
        raise

    if result.status == "language_generation_failed":
        return language_failure_response(payload, bundle, result)
    if result.status == "ok" and result.content.strip() and not language_matches_target(result.content, result.response_language):
        return language_failure_response(payload, bundle, result)
    if result.status != "ok" or not result.content.strip():
        return {
            "status": "unavailable",
            "task": payload.task,
            "model_status": "unavailable",
            "result": {"summary": "", "answer": "", "error": "live_model_unavailable", "customer_safe": True},
            "missing_data": [],
            "confidence": "low",
            "citations": [],
            "sample_mode": bool(bundle.get("sample_mode")),
            "preferred_language": payload.preferred_language,
            "response_language": result.response_language,
            "task_profile": result.profile,
            "intelligence_profile": commercial.get("profile", "essential"),
        }

    body = local_plain_body(result.content.strip(), context, question=payload.question)
    return {
        "status": "completed",
        "task": payload.task,
        "model_status": "live",
        "result": body,
        "missing_data": body["missing_data"],
        "confidence": body["confidence"],
        "citations": [
            citation.model_dump(mode="python") if hasattr(citation, "model_dump") else citation
            for citation in context.citations[:8]
        ],
        "sample_mode": bool(bundle.get("sample_mode")),
        "preferred_language": payload.preferred_language,
        "response_language": result.response_language,
        "task_profile": result.profile,
        "intelligence_profile": commercial.get("profile", "essential"),
    }


@router.post("/ai/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> ChatResponse:
    context = _get_evidence_context(db=db, tenant_id=tenant_id, block_id=payload.block_id, workspace_id=payload.workspace_id)
    language = resolve_language(payload.preferred_language, payload.message)
    fallback = _deterministic_body(context, user_instruction=payload.message, task="chat")
    router_model = ModelRouter()
    evidence_json = json.dumps(context.model_dump(mode="python"), default=str)[:9000]
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{language.instruction}\n\nUser request: {payload.message}\n\nEvidence context JSON: {evidence_json}"},
    ]
    result, _selection = await router_model.run(task="chat", messages=messages, temperature=payload.temperature, response_format={"type": "json_object"})
    body = parse_model_json(result.content)
    if result.status != "ok" or result.demo_fallback or body.get("_safe_mode"):
        body = fallback
    else:
        body = _normalize(body, fallback)
    output = str(body.get("summary") or body.get("answer") or fallback["summary"])
    return ChatResponse(
        status="ok" if result.status == "ok" else "unavailable",
        output=output,
        provider=result.provider,
        model=result.model,
        demo_fallback=result.demo_fallback,
        evidence_context=context,
        citations=context.citations,
        verification=_verification(result.status, context),
        raw={**body, "language": language.__dict__},
    )

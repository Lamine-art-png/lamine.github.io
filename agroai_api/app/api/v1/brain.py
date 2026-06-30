"""AGRO-AI operating intelligence endpoint."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.services.ai_gateway import clean_model_text, parse_model_json
from app.services.intelligence_context import build_intelligence_context
from app.services.model_router import ModelRouter

router = APIRouter(prefix="/intelligence", tags=["agro-ai-intelligence"])


class BrainRunRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=12000)
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)


HOSTED_PROMPT = """
You are AGRO-AI's enterprise operating intelligence layer. Use workspace evidence, separate known from missing data, and return valid JSON with summary, answer, work_completed, evidence_used, missing_evidence, recommendations, next_actions, risk_flags, confidence, and customer_safe.
"""

LOCAL_PROMPT = """
/no_think
You are AGRO-AI, an agriculture operations assistant. Answer the user's actual question in normal customer-facing text. Keep it brief, useful, and natural. Do not return JSON. Do not repeat generic fallback text. Work only from supplied context. If data is missing, name the missing data and the next useful step.
"""


def _trim_history(history: list[dict[str, Any]], limit: int, max_chars: int) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    for row in history[-limit:]:
        role = str(row.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if content:
            clean.append({"role": role, "content": content[:max_chars]})
    return clean


def _dedupe_models(models: list[str | None]) -> list[str]:
    clean: list[str] = []
    for model in models:
        value = (model or "").strip()
        if value and value not in clean:
            clean.append(value)
    return clean


def _compact(value: Any, max_chars: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact(item, 350) for key, item in list(value.items())[:8]}
    if isinstance(value, list):
        return [_compact(item, 250) for item in value[:3]]
    if isinstance(value, str):
        return value[:max_chars]
    return value


def _needs_missing_evidence(question: str) -> bool:
    q = (question or "").lower()
    operational_terms = [
        "water", "irrigat", "field", "telemetry", "compliance", "report", "evidence", "upload",
        "soil", "weather", "et", "controller", "wiseconn", "talgil", "john deere", "operations center",
    ]
    return any(term in q for term in operational_terms)


def _body_from_local_text(value: str, evidence_context: Any, question: str) -> dict[str, Any]:
    answer = clean_model_text(value)
    if not answer:
        answer = "I can help. Tell me the field, crop, and decision you are trying to make, and I will separate what we know from what is missing."
    missing = list(getattr(evidence_context, "missing_data", []) or [])[:3] if _needs_missing_evidence(question) else []
    return {
        "summary": answer,
        "answer": answer,
        "work_completed": [],
        "evidence_used": [],
        "missing_evidence": missing,
        "operating_plan": [],
        "recommendations": [],
        "next_actions": [],
        "risk_flags": [],
        "confidence": "low" if missing else "medium",
        "customer_safe": True,
    }


def _fallback(context_bundle: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    evidence_summary = context_bundle.get("evidence_summary") or {}
    evidence_context = context_bundle.get("evidence_context")
    missing = list(getattr(evidence_context, "missing_data", []) or evidence_summary.get("missing_source_types") or [])
    return {
        "summary": "Live model reasoning did not complete. Check the local model runtime and rerun the request.",
        "answer": "Live model reasoning did not complete. Check the local model runtime and rerun the request.",
        "work_completed": ["Loaded tenant-scoped workspace context."],
        "evidence_used": [f"Workspace evidence records: {evidence_summary.get('evidence_count', 0)}"],
        "missing_evidence": missing or ["live model response"],
        "operating_plan": [],
        "recommendations": [],
        "next_actions": ["Run model smoke test", "Rerun Ask AGRO-AI"],
        "risk_flags": ([str(error)[:240]] if error else []),
        "confidence": "low",
        "customer_safe": True,
    }


@router.get("/brain/model-smoke")
async def model_smoke() -> dict[str, Any]:
    model_router = ModelRouter()
    selected = model_router.select("chat")
    is_local = model_router.mode() == "ollama"
    result, selection = await model_router.run(
        task="chat",
        messages=[
            {"role": "system", "content": LOCAL_PROMPT if is_local else HOSTED_PROMPT},
            {"role": "user", "content": "QUESTION: Say that AGRO-AI live model routing is working in one short sentence."},
        ],
        temperature=0.1,
        response_format=None if is_local else {"type": "json_object"},
    )
    body = _body_from_local_text(result.content, None, "model smoke") if is_local else parse_model_json(result.content)
    live = result.status == "ok" and not result.demo_fallback and bool(body.get("summary") or body.get("answer"))
    return {
        "status": "ok" if live else "failed",
        "live_model_response": live,
        "provider": result.provider,
        "selected_model": result.model or selection.model or selected.model,
        "gateway_status": result.status,
        "demo_fallback": result.demo_fallback,
        "error": result.error,
        "summary": body.get("summary") or body.get("answer") or "",
    }


@router.post("/brain/run")
async def brain_run(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        context_bundle = build_intelligence_context(
            db=db,
            tenant_id=tenant_id,
            user=user,
            workspace_id=payload.workspace_id,
            field_id=payload.field_id,
            audience=payload.audience,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    model_router = ModelRouter()
    evidence_context = context_bundle["evidence_context"]
    is_local = model_router.mode() == "ollama"
    evidence_limit = 2 if is_local else 90
    citation_limit = 2 if is_local else 40

    missing_data = list(getattr(evidence_context, "missing_data", []) or [])[:3]
    evidence_summary = context_bundle.get("evidence_summary") or {}
    workspace = context_bundle.get("workspace") or {}
    request_context = {
        "question": payload.question,
        "workspace": _compact(workspace, 500),
        "evidence_summary": _compact(evidence_summary, 500),
        "uploaded_evidence": payload.uploaded_evidence[:1 if is_local else 10],
        "missing_data": missing_data,
        "tenant_context": {
            "fields": _compact(context_bundle.get("fields") or {}, 450),
            "evidence": _compact(getattr(evidence_context, "evidence", [])[:evidence_limit], 350),
        },
    }
    if is_local:
        request_context = _compact(request_context, 1600)

    messages: list[dict[str, str]] = [{"role": "system", "content": LOCAL_PROMPT if is_local else HOSTED_PROMPT}]
    messages.extend(_trim_history(payload.history, limit=1 if is_local else 12, max_chars=300 if is_local else 2500))
    if is_local:
        user_content = (
            f"QUESTION: {payload.question}\n\n"
            f"WORKSPACE_CONTEXT: {json.dumps(request_context, default=str)[:1600]}\n\n"
            "Answer QUESTION directly in normal text only. If the exact number or decision needs missing data, say the missing fields and the next best action. Do not repeat generic onboarding copy."
        )
    else:
        user_content = "Run the operating intelligence layer on this request. Return the required JSON shape only.\n\n" + json.dumps(request_context, default=str)[:180000]
    messages.append({"role": "user", "content": user_content})

    models = _dedupe_models([model_router.reasoning_model, model_router.default_model, *model_router.fallback_models])
    last_error: str | None = None
    last_result = None
    attempts: list[dict[str, Any]] = []

    for model in models:
        if is_local and "/" in model:
            continue
        result = await model_router.gateway.chat(
            messages,
            temperature=0.1 if is_local else 0.42,
            response_format=None if is_local else {"type": "json_object"},
            model_override=model,
        )
        last_result = result
        attempts.append({"model": model, "status": result.status, "demo_fallback": result.demo_fallback, "provider": result.provider, "error": (result.error or "")[:500]})
        if result.status != "ok" or result.demo_fallback:
            last_error = result.error or result.status
            continue
        body = _body_from_local_text(result.content, evidence_context, payload.question) if is_local else parse_model_json(result.content)
        if body.get("summary") or body.get("answer"):
            if not body.get("summary"):
                body["summary"] = body.get("answer")
            if not body.get("answer"):
                body["answer"] = body.get("summary")
            body.setdefault("missing_evidence", [] if is_local else getattr(evidence_context, "missing_data", []))
            body.setdefault("confidence", "low" if body.get("missing_evidence") else "medium")
            body["customer_safe"] = True
            return {
                "status": "completed",
                "model_status": "live",
                "result": body,
                "citations": [citation.model_dump(mode="python") for citation in getattr(evidence_context, "citations", [])[:citation_limit]],
                "evidence_summary": evidence_summary,
                "missing_data": body.get("missing_evidence") or [],
                "confidence": body.get("confidence") or "low",
                "internal_debug": {"selected_model": result.model, "attempts": attempts, "local_ollama_mode": is_local},
            }
        last_error = "model_returned_unusable_body"
        attempts[-1]["error"] = last_error

    fallback = _fallback(context_bundle, last_error)
    return {
        "status": "unavailable",
        "model_status": "fallback",
        "result": fallback,
        "citations": [citation.model_dump(mode="python") for citation in getattr(evidence_context, "citations", [])[:citation_limit]],
        "evidence_summary": evidence_summary,
        "missing_data": fallback.get("missing_evidence") or getattr(evidence_context, "missing_data", []),
        "confidence": "low",
        "internal_status": getattr(last_result, "status", None) if last_result else "not_configured",
        "internal_debug": {"last_error": last_error, "attempts": attempts, "local_ollama_mode": is_local},
    }

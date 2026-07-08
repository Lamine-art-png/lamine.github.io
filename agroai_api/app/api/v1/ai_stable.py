from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.ai import _deterministic_body, _get_evidence_context, _verification
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.schemas.ai import ChatRequest, ChatResponse
from app.services.ai_gateway import parse_model_json
from app.services.language import resolve_language
from app.services.model_router import ModelRouter

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

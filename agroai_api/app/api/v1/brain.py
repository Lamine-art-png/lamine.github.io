"""Live AGRO-AI operating brain endpoint."""
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
from app.services.ai_gateway import parse_model_json
from app.services.intelligence_context import build_intelligence_context
from app.services.model_router import ModelRouter

router = APIRouter(prefix="/intelligence", tags=["agro-ai-brain"])


class BrainRunRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=12000)
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)


BRAIN_SYSTEM_PROMPT = """
You are AGRO-AI Brain, the enterprise operating intelligence layer inside AGRO-AI.

You are not a canned chatbot. You operate like a serious agriculture operations lead with model intelligence behind the product. Your job is to take fragmented workspace context, uploaded files, telemetry and evidence summaries, compliance requirements, field operations, and conversation history, then turn them into useful work.

Core operating domains:
- irrigation and water-use decisions;
- field operations and operator tasking;
- evidence reconciliation and source provenance;
- compliance and assurance packets;
- customer reports and executive briefs;
- connector and upload readiness;
- scattered dataset analysis and cleanup planning.

Rules:
- Answer the user's actual question first in natural language.
- Do not expose provider, model, runtime, fallback, JSON, internal route, or debug language to the customer.
- Do not repeat a fixed template. Use the user's request and the workspace evidence.
- Separate measured, uploaded, sample, inferred, stale, missing, and live data.
- If real-world data is missing, still do useful planning work: classify the evidence, identify blockers, draft the operating plan, and create next actions.
- Do not invent telemetry, integrations, acreage, water use, compliance status, savings, or customer facts.
- Use uploaded evidence summaries when present. Treat uploads as newly ingested evidence, not as invisible attachments.
- Return valid JSON only. No markdown fences.

Required JSON shape:
{
  "summary": "natural answer first",
  "answer": "full natural answer if more detail is needed",
  "work_completed": [],
  "evidence_used": [],
  "missing_evidence": [],
  "operating_plan": [],
  "recommendations": [],
  "next_actions": [],
  "risk_flags": [],
  "confidence": "low|medium|high",
  "customer_safe": true
}
"""


def _trim_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    for row in history[-12:]:
        role = str(row.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if content:
            clean.append({"role": role, "content": content[:2500]})
    return clean


def _dedupe_models(models: list[str | None]) -> list[str]:
    clean: list[str] = []
    for model in models:
        value = (model or "").strip()
        if value and value not in clean:
            clean.append(value)
    return clean


def _brain_fallback(payload: BrainRunRequest, context_bundle: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    evidence_summary = context_bundle.get("evidence_summary") or {}
    evidence_context = context_bundle.get("evidence_context")
    missing = list(getattr(evidence_context, "missing_data", []) or evidence_summary.get("missing_source_types") or [])
    uploaded = payload.uploaded_evidence or []
    first_missing = missing[0] if missing else "live model response"
    return {
        "summary": "I can read the workspace context and uploaded evidence, but live model reasoning did not complete. I will not pretend the full AGRO-AI brain ran.",
        "answer": "I can read the workspace context and uploaded evidence, but live model reasoning did not complete. The safe move is to keep this in review, resolve the first blocker, and rerun the request once live inference returns a usable answer.",
        "work_completed": [
            "Loaded tenant-scoped workspace context.",
            "Attached uploaded evidence to the request." if uploaded else "Checked for uploaded evidence attached to the request.",
            "Separated available context from evidence that is still missing.",
        ],
        "evidence_used": [
            f"Workspace evidence records: {evidence_summary.get('evidence_count', 0)}",
            f"Data sources: {evidence_summary.get('source_count', 0)}",
            *[str(item.get("filename") or item.get("name") or item.get("data_source", {}).get("filename") or "uploaded evidence") for item in uploaded[:6]],
        ],
        "missing_evidence": missing or ["live model response"],
        "operating_plan": [
            f"Resolve the first blocker: {first_missing}.",
            "Attach source provenance to every claim before generating reports or decisions.",
            "Rerun AGRO-AI Brain after model routing is live.",
        ],
        "recommendations": [
            "Do not use this as a final irrigation, compliance, or customer-facing decision until live inference completes.",
            "Use uploads/connectors to increase workspace evidence coverage, then rerun the request.",
        ],
        "next_actions": ["Check model routing", "Upload or connect missing evidence", "Rerun AGRO-AI Brain"],
        "risk_flags": ["Live model inference did not complete."] + ([str(error)[:240]] if error else []),
        "confidence": "low",
        "customer_safe": True,
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
    request_context = {
        "question": payload.question,
        "audience": payload.audience or "operator",
        "workspace": context_bundle.get("workspace") or {},
        "evidence_summary": context_bundle.get("evidence_summary") or {},
        "uploaded_evidence": payload.uploaded_evidence[:10],
        "missing_data": getattr(evidence_context, "missing_data", []),
        "tenant_context": {
            "readiness": context_bundle.get("readiness") or {},
            "fields": context_bundle.get("fields") or {},
            "exceptions": context_bundle.get("exceptions") or {},
            "decisions": context_bundle.get("decisions") or {},
            "reports": context_bundle.get("reports") or {},
            "evidence": getattr(evidence_context, "evidence", [])[:90],
            "citations": [citation.model_dump(mode="python") for citation in getattr(evidence_context, "citations", [])[:40]],
        },
    }

    messages: list[dict[str, str]] = [{"role": "system", "content": BRAIN_SYSTEM_PROMPT}]
    messages.extend(_trim_history(payload.history))
    messages.append(
        {
            "role": "user",
            "content": "Run AGRO-AI Brain on this request. Work naturally, but return the required JSON shape only.\n\n"
            + json.dumps(request_context, default=str)[:180000],
        }
    )

    models = _dedupe_models([model_router.reasoning_model, model_router.default_model, *model_router.fallback_models])
    last_error: str | None = None
    last_result = None

    for model in models:
        result = await model_router.gateway.chat(
            messages,
            temperature=0.42,
            response_format={"type": "json_object"},
            model_override=model,
        )
        last_result = result
        if result.status != "ok" or result.demo_fallback:
            last_error = result.error or result.status
            continue
        body = parse_model_json(result.content)
        if body.get("summary") or body.get("answer"):
            if not body.get("summary"):
                body["summary"] = body.get("answer")
            if not body.get("answer"):
                body["answer"] = body.get("summary")
            body.setdefault("work_completed", [])
            body.setdefault("evidence_used", [])
            body.setdefault("missing_evidence", getattr(evidence_context, "missing_data", []))
            body.setdefault("operating_plan", body.get("agent_plan") or body.get("recommendations") or [])
            body.setdefault("next_actions", [])
            body.setdefault("risk_flags", [])
            body.setdefault("confidence", "low" if getattr(evidence_context, "missing_data", []) else "medium")
            body["customer_safe"] = True
            return {
                "status": "completed",
                "model_status": "live",
                "result": body,
                "citations": [citation.model_dump(mode="python") for citation in getattr(evidence_context, "citations", [])],
                "evidence_summary": context_bundle.get("evidence_summary") or {},
                "missing_data": body.get("missing_evidence") or getattr(evidence_context, "missing_data", []),
                "confidence": body.get("confidence") or "low",
            }
        last_error = "model_returned_unusable_body"

    fallback = _brain_fallback(payload, context_bundle, last_error)
    return {
        "status": "unavailable",
        "model_status": "fallback",
        "result": fallback,
        "citations": [citation.model_dump(mode="python") for citation in getattr(evidence_context, "citations", [])],
        "evidence_summary": context_bundle.get("evidence_summary") or {},
        "missing_data": fallback.get("missing_evidence") or getattr(evidence_context, "missing_data", []),
        "confidence": "low",
        "internal_status": getattr(last_result, "status", None) if last_result else "not_configured",
    }

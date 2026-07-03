"""Compact model helpers for Ask AGRO-AI."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.schemas.ai import EvidenceContext
from app.services.ai_gateway import AIGateway
from app.services.intelligence_context import build_intelligence_context
from app.services.language import localized_safe_fallback, looks_english, resolve_language
from app.services.model_router import ModelRouter

router = APIRouter(prefix="/intelligence/brain", tags=["intelligence"])

LOCAL_SYSTEM_PROMPT = """You are AGRO-AI, a serious agriculture operations intelligence operator.
Answer in normal customer-facing text. No JSON. No debug labels. No <think> tags.
Adapt to the user: short when casual, detailed when they ask for analysis, reports, decisions, documents, checklists, or plans.
For reports, write like an institutional compliance/reporting consultant: structured, precise, evidence-led, reviewer-safe, and board-ready.
If evidence is thin, continue with a useful draft and clearly mark assumptions instead of refusing.
Use only supplied context and uploaded evidence. Do not invent telemetry, acreage, integrations, water use, compliance status, savings, or customer facts.
Language rule is mandatory: answer in the selected or detected response language supplied in the user message. Do not answer in English unless that response language is English or the user explicitly asks for English.
Do not repeat the same answer. Use recent history to move the work forward."""

LANGUAGE_NAMES = {
    "auto": "the user's language",
    "en": "English", "fr": "French", "es": "Spanish", "pt": "Portuguese", "ar": "Arabic", "zh": "Chinese", "hi": "Hindi", "bn": "Bengali", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "de": "German", "it": "Italian", "tr": "Turkish", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai", "sw": "Swahili", "wo": "Wolof", "ff": "Fulfulde", "ha": "Hausa", "yo": "Yoruba", "ig": "Igbo", "am": "Amharic", "fa": "Persian", "ur": "Urdu", "pl": "Polish", "nl": "Dutch", "uk": "Ukrainian", "ro": "Romanian", "el": "Greek", "he": "Hebrew",
}

class BrainRunRequest(BaseModel):
    task: str = "chat"
    question: str = Field(..., min_length=1)
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    preferred_language: str | None = None

MISSING_EVIDENCE_TERMS = ("how much water", "water should", "irrigat", "apply", "compliance", "diagnose", "field diagnosis", "water accounting", "evidence missing", "missing evidence", "what evidence")
CASUAL_TERMS = ("hi", "hello", "hey", "what can you do", "what are you good at", "do you know john deere", "john deere", "capabilities")
REPORT_TERMS = ("report", "pdf", "document", "packet", "brief", "analysis", "memo", "customer-ready", "executive")

def is_local_ai() -> bool:
    return (settings.AI_PROVIDER or "").strip().lower() == "ollama"

def _short(value: Any, limit: int = 300) -> str:
    return str(value or "").replace("\n", " ").strip()[:limit].rstrip()

def _language_name(code: str | None) -> str:
    root = (code or "auto").split("-")[0].lower().strip() or "auto"
    return LANGUAGE_NAMES.get(root, f"language code {root}")

def _script_hint(question: str) -> str:
    text = question or ""
    if re.search(r"[\u0600-\u06ff]", text): return "Arabic/Persian/Urdu script detected"
    if re.search(r"[\u0400-\u04ff]", text): return "Cyrillic script detected"
    if re.search(r"[\u4e00-\u9fff]", text): return "Chinese script detected"
    if re.search(r"[\u3040-\u30ff]", text): return "Japanese script detected"
    if re.search(r"[\uac00-\ud7af]", text): return "Korean script detected"
    if re.search(r"[\u0900-\u097f]", text): return "Indic script detected"
    return "No non-Latin script detected"

def actual_missing_data_only(items: list[str] | tuple[str, ...] | None) -> list[str]:
    blocked = {"structured model json", "structured model json object"}
    clean: list[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if text and text.lower() not in blocked:
            clean.append(text)
    return list(dict.fromkeys(clean))

def wants_report(question: str) -> bool:
    normalized = " ".join(str(question or "").lower().split())
    return any(term in normalized for term in REPORT_TERMS)

def should_surface_missing_evidence(question: str) -> bool:
    normalized = " ".join(str(question or "").lower().split())
    if not normalized or any(term in normalized for term in CASUAL_TERMS): return False
    return wants_report(normalized) or any(term in normalized for term in MISSING_EVIDENCE_TERMS)

def readable_missing_label(value: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    return {"live WiseConn credentials": "WiseConn connection", "live Talgil credentials": "Talgil connection", "confirmed live telemetry stream": "confirmed live telemetry", "compliance water accounting": "compliance water accounting data"}.get(text, text)

def compact_uploaded_evidence(items: list[dict[str, Any]] | None, *, max_items: int = 5) -> list[str]:
    compact: list[str] = []
    for item in (items or [])[:max_items]:
        filename = _short(item.get("filename") or item.get("name"), 120)
        source_type = _short(item.get("file_type") or item.get("source_type") or item.get("content_type"), 80)
        status = _short(item.get("import_status") or item.get("status"), 80)
        rows = item.get("rows") or item.get("rows_parsed")
        columns = item.get("columns") or []
        preview = _short(item.get("parsed_preview") or item.get("text_preview") or item.get("preview"), 500)
        bits = [filename, source_type, f"status={status}" if status else ""]
        if rows is not None: bits.append(f"rows={rows}")
        if columns: bits.append(f"columns={', '.join(str(column) for column in columns[:10])}")
        if preview: bits.append(f"preview={preview}")
        compact.append(" - ".join(part for part in bits if part))
    return compact

def attach_uploaded_evidence(context: EvidenceContext, uploaded: list[dict[str, Any]]) -> None:
    for item in uploaded[:10]:
        if isinstance(item, dict):
            context.evidence.append({"type": "uploaded_file", "filename": item.get("filename") or item.get("name"), "source_type": item.get("file_type") or item.get("source_type") or item.get("content_type"), "size_bytes": item.get("size_bytes"), "import_status": item.get("import_status") or item.get("status"), "rows_parsed": item.get("rows") or item.get("rows_parsed"), "columns": item.get("columns") or [], "parsed_preview": item.get("parsed_preview") or item.get("text_preview") or item.get("preview"), "warnings": item.get("warnings") or [], "source": "chat_upload"})

def compact_evidence_items(context: EvidenceContext, *, max_items: int = 5) -> list[str]:
    compact: list[str] = []
    for item in context.evidence[:max_items]:
        item_type = _short(item.get("type"), 60)
        source = _short(item.get("source") or item.get("provider"), 60)
        name = _short(item.get("name") or item.get("title") or item.get("summary") or item.get("filename") or item.get("parsed_preview"), 260)
        if item_type == "telemetry_recent":
            records = item.get("records") or []
            name = f"{len(records)} recent telemetry records available" if records else "No recent telemetry records"
        if item_type == "recommendation_recent": name = "Recent recommendation record is available"
        compact.append(" - ".join(part for part in [item_type, name, f"source={source}" if source else ""] if part))
    return compact

def compact_local_messages(*, question: str, context: EvidenceContext, history: list[dict[str, Any]] | None = None, audience: str | None = None, uploaded_evidence: list[dict[str, Any]] | None = None, preferred_language: str | None = None) -> list[dict[str, str]]:
    language = resolve_language(preferred_language, question)
    evidence = compact_evidence_items(context, max_items=5)
    uploads = compact_uploaded_evidence(uploaded_evidence, max_items=5)
    missing = [readable_missing_label(item) for item in actual_missing_data_only(context.missing_data)] if should_surface_missing_evidence(question) else []
    report_instruction = "The user appears to want a report/document. Produce a compliance-grade operating report draft with headings, evidence register, control considerations, risks/assumptions, recommended actions, and a reviewer-safe note. Do not make unsupported claims." if wants_report(question) else "Produce the most useful direct answer for the user's request."
    lines = [
        f"Question: {_short(question, 900)}",
        language.instruction,
        f"Preferred portal language code: {preferred_language or 'auto'}. Mandatory response language code: {language.response_code}. Mandatory response language name: {language.response_name}.",
        f"Detected script hint: {_script_hint(question)}.",
        "Hard rule: the final answer must be written in the mandatory response language, not English, unless English is the mandatory response language.",
        f"Audience: {_short(audience, 80) if audience else 'operator'}",
        f"Workspace: {_short(context.workspace_id or 'current workspace', 120)}",
        f"Crop/region: {_short(context.crop_type or 'unknown', 80)} / {_short(context.region or 'unknown', 80)}",
        "Evidence:", *(evidence or ["No compact evidence records are available."]),
        "Imported files:", *(uploads or ["No imported files attached to this request."]),
        "Missing data to mention only if relevant:", *(missing[:6] or ["No missing evidence listed."]),
        "Response instruction:", report_instruction,
    ]
    context_text = "\n".join(lines)[:6200]
    recent_history = []
    for row in (history or [])[-6:]:
        role = "assistant" if row.get("role") == "assistant" else "user"
        content = _short(row.get("content"), 900)
        if content: recent_history.append({"role": role, "content": content})
    return [{"role": "system", "content": LOCAL_SYSTEM_PROMPT}, *recent_history, {"role": "user", "content": context_text}]

def local_plain_body(answer: str, context: EvidenceContext, *, question: str = "") -> dict[str, Any]:
    missing = [readable_missing_label(item) for item in actual_missing_data_only(context.missing_data)] if should_surface_missing_evidence(question) else []
    return {"summary": answer, "answer": answer, "work_completed": [], "evidence_used": [], "missing_evidence": missing, "missing_data": missing, "recommendations": [], "next_actions": [], "risk_flags": [], "confidence": "low" if missing else "medium", "customer_safe": True}

async def _rewrite_if_needed(model_router: ModelRouter, answer: str, response_language: str, response_language_name: str) -> str:
    if response_language == "en" or not looks_english(answer):
        return answer
    rewrite_messages = [
        {"role": "system", "content": f"Translate/rewrite the user's text into {response_language_name}. Return only the rewritten answer. Keep agriculture, irrigation, telemetry, compliance, and water-accounting terms precise. Do not add new facts."},
        {"role": "user", "content": answer[:4000]},
    ]
    result, _selection = await model_router.run(task="chat", messages=rewrite_messages, temperature=0.05, response_format=None)
    rewritten = str(result.content or "").strip()
    if result.status == "ok" and rewritten and not looks_english(rewritten):
        return rewritten
    return localized_safe_fallback(response_language)

@router.post("/run")
async def brain_run(payload: BrainRunRequest, tenant_id: str = Depends(require_current_tenant_id), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    language = resolve_language(payload.preferred_language, payload.question)
    context_bundle = build_intelligence_context(db=db, tenant_id=tenant_id, user=user, workspace_id=payload.workspace_id, field_id=payload.field_id, audience=payload.audience)
    context = context_bundle["evidence_context"]
    attach_uploaded_evidence(context, payload.uploaded_evidence)
    model_router = ModelRouter()
    messages = compact_local_messages(question=payload.question, context=context, history=payload.history[-6:], audience=payload.audience, uploaded_evidence=payload.uploaded_evidence, preferred_language=language.response_code)
    result, selection = await model_router.run(task="chat", messages=messages, temperature=0.18, response_format=None)
    if result.status != "ok" or result.demo_fallback:
        answer = localized_safe_fallback(language.response_code)
    else:
        answer = str(result.content or "").strip() or localized_safe_fallback(language.response_code)
        answer = await _rewrite_if_needed(model_router, answer, language.response_code, language.response_name)
    body = local_plain_body(answer, context, question=payload.question)
    model_status = "live" if result.status == "ok" and not result.demo_fallback else "fallback"
    return {"status": "completed" if result.status == "ok" or result.demo_fallback else "unavailable", "task": payload.task, "model_status": model_status, "result": body, "missing_data": body["missing_data"], "confidence": body["confidence"], "citations": [citation.model_dump(mode="python") if hasattr(citation, "model_dump") else citation for citation in context.citations[:8]], "sample_mode": bool(context_bundle.get("sample_mode")), "selected_model": selection.model, "preferred_language": payload.preferred_language, "response_language": language.response_code}

@router.get("/model-smoke")
async def model_smoke() -> dict[str, Any]:
    gateway = AIGateway()
    model_router = ModelRouter()
    selection = model_router.select("chat")
    live = False
    if gateway.is_configured and gateway.provider == "ollama":
        result = await gateway.chat([{"role": "system", "content": "Reply with OK only."}, {"role": "user", "content": "OK"}], response_format=None, model_override=selection.model)
        live = result.status == "ok" and bool(result.content)
    return {"live_model_response": live, "provider": gateway.provider or "offline", "selected_model": selection.model or gateway.model}

from app.api.v1.conversations import router as conversation_history_router  # noqa: E402
router.include_router(conversation_history_router)

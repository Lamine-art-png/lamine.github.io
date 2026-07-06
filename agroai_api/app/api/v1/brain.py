"""Ask AGRO-AI: adaptive, evidence-grounded, commercially controlled conversation."""
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
from app.models.saas import Organization, User
from app.schemas.ai import EvidenceContext
from app.services.intelligence_context import build_intelligence_context
from app.services.language import language_matches_target, resolve_language
from app.services.live_intelligence import LiveIntelligence
from app.services.quota import commit_reservation, release_reservation, reserve_quota

router = APIRouter(prefix="/intelligence/brain", tags=["intelligence"])


class BrainRunRequest(BaseModel):
    task: str = "chat"
    question: str = Field(..., min_length=1)
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    preferred_language: str | None = None


MISSING_EVIDENCE_TERMS = (
    "how much water", "water should", "irrigat", "apply", "compliance",
    "diagnose", "field diagnosis", "water accounting", "evidence missing",
    "missing evidence", "what evidence", "combien d'eau", "cuánta agua",
    "quanta água",
)
CASUAL_TERMS = (
    "hi", "hello", "hey", "bonjour", "hola", "salut", "olá",
    "what can you do", "what are you good at", "capabilities",
)


def is_local_ai() -> bool:
    return (settings.AI_PROVIDER or "").strip().lower() == "ollama"


def _short(value: Any, limit: int = 900) -> str:
    return str(value or "").replace("\n", " ").strip()[:limit]


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def actual_missing_data_only(items: list[str] | tuple[str, ...] | None) -> list[str]:
    blocked = {"structured model json", "structured model json object"}
    output: list[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if text and text.lower() not in blocked and text not in output:
            output.append(text)
    return output


def should_surface_missing_evidence(question: str) -> bool:
    text = _normalized(question)
    if not text or any(term in text for term in CASUAL_TERMS):
        return False
    return any(term in text for term in MISSING_EVIDENCE_TERMS) or any(
        term in text for term in ("report", "audit", "evidence", "proof", "compliance")
    )


def readable_missing_label(value: str) -> str:
    text = str(value or "").strip().replace("_", " ")
    return {
        "live WiseConn credentials": "WiseConn connection",
        "live Talgil credentials": "Talgil connection",
        "confirmed live telemetry stream": "confirmed live telemetry",
        "compliance water accounting": "compliance water accounting data",
    }.get(text, text)


def compact_uploaded_evidence(items: list[dict[str, Any]] | None, *, max_items: int = 6) -> list[str]:
    compact: list[str] = []
    for item in (items or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        filename = _short(item.get("filename") or item.get("name"), 140)
        source_type = _short(item.get("file_type") or item.get("source_type") or item.get("content_type"), 90)
        status = _short(item.get("import_status") or item.get("status"), 80)
        rows = item.get("rows") or item.get("rows_parsed")
        columns = item.get("columns") or []
        preview = _short(item.get("parsed_preview") or item.get("text_preview") or item.get("preview"), 700)
        bits = [filename, source_type, f"status={status}" if status else ""]
        if rows is not None:
            bits.append(f"rows={rows}")
        if columns:
            bits.append(f"columns={', '.join(str(column) for column in columns[:12])}")
        if preview:
            bits.append(f"preview={preview}")
        compact.append(" | ".join(part for part in bits if part))
    return compact


def attach_uploaded_evidence(context: EvidenceContext, uploaded: list[dict[str, Any]]) -> None:
    for item in uploaded[:10]:
        if not isinstance(item, dict):
            continue
        context.evidence.append({
            "type": "uploaded_file",
            "filename": item.get("filename") or item.get("name"),
            "source_type": item.get("file_type") or item.get("source_type") or item.get("content_type"),
            "size_bytes": item.get("size_bytes"),
            "import_status": item.get("import_status") or item.get("status"),
            "rows_parsed": item.get("rows") or item.get("rows_parsed"),
            "columns": item.get("columns") or [],
            "parsed_preview": item.get("parsed_preview") or item.get("text_preview") or item.get("preview"),
            "warnings": item.get("warnings") or [],
            "source": "chat_upload",
        })


def compact_evidence_items(context: EvidenceContext, *, max_items: int = 8) -> list[str]:
    compact: list[str] = []
    for item in context.evidence[:max_items]:
        if not isinstance(item, dict):
            continue
        item_type = _short(item.get("type"), 70)
        source = _short(item.get("source") or item.get("provider"), 80)
        name = _short(
            item.get("name") or item.get("title") or item.get("summary")
            or item.get("filename") or item.get("parsed_preview"), 500,
        )
        if item_type == "telemetry_recent":
            records = item.get("records") or []
            name = f"{len(records)} recent telemetry records available" if records else "No recent telemetry records"
        if item_type == "recommendation_recent":
            name = "Recent recommendation record is available"
        compact.append(" | ".join(part for part in (item_type, name, f"source={source}" if source else "") if part))
    return compact


def compact_local_messages(
    *,
    question: str,
    context: EvidenceContext,
    history: list[dict[str, Any]] | None = None,
    audience: str | None = None,
    uploaded_evidence: list[dict[str, Any]] | None = None,
    preferred_language: str | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    normalized_question = _normalized(question)
    for item in (history or [])[-12:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = _short(item.get("content"), 2200)
        if not content:
            continue
        if role == "user" and _normalized(content) == normalized_question:
            continue
        rows.append({"role": role, "content": content})

    evidence = compact_evidence_items(context)
    uploads = compact_uploaded_evidence(uploaded_evidence)
    missing = [readable_missing_label(item) for item in actual_missing_data_only(context.missing_data)] if should_surface_missing_evidence(question) else []
    language = resolve_language(preferred_language, question)

    context_lines = [
        f"Exact current question: {question}",
        f"Preferred portal language code: {preferred_language or 'auto'}",
        language.instruction,
        f"Audience: {audience or 'operator'}",
        f"Workspace: {context.workspace_id or 'current workspace'}",
        f"Crop: {context.crop_type or 'unknown'}",
        f"Region: {context.region or 'unknown'}",
        "Relevant workspace evidence:",
    ]
    context_lines.extend([f"- {item}" for item in evidence] if evidence else ["- none supplied"])
    context_lines.append("Imported file context:")
    context_lines.extend([f"- {item}" for item in uploads] if uploads else ["- none supplied"])
    context_lines.append("Relevant missing evidence:")
    context_lines.extend([f"- {item}" for item in missing[:8]] if missing else ["- none listed"])
    context_lines.append(
        "Answer the exact current question. Use prior turns as conversation context. "
        "Do not repeat an earlier answer unless the user asks you to repeat it. "
        "Do not force an evidence-gap template onto unrelated questions."
    )
    rows.append({"role": "user", "content": "\n".join(context_lines)[:12000]})
    return rows


def local_plain_body(answer: str, context: EvidenceContext, *, question: str = "") -> dict[str, Any]:
    missing = [readable_missing_label(item) for item in actual_missing_data_only(context.missing_data)] if should_surface_missing_evidence(question) else []
    return {
        "summary": answer,
        "answer": answer,
        "work_completed": [],
        "evidence_used": [],
        "missing_evidence": missing,
        "missing_data": missing,
        "recommendations": [],
        "next_actions": [],
        "risk_flags": [],
        "confidence": "low" if missing else "medium",
        "customer_safe": True,
    }


def language_failure_response(payload: BrainRunRequest, bundle: dict[str, Any], result) -> dict[str, Any]:
    commercial = bundle.get("commercial_intelligence") or {}
    return {
        "status": "language_generation_failed",
        "task": payload.task,
        "model_status": "language_generation_failed",
        "result": {
            "summary": "",
            "answer": "",
            "error": "language_generation_failed",
            "customer_safe": True,
        },
        "missing_data": [],
        "confidence": "low",
        "citations": [],
        "sample_mode": bool(bundle.get("sample_mode")),
        "preferred_language": payload.preferred_language,
        "response_language": result.response_language,
        "task_profile": result.profile,
        "intelligence_profile": commercial.get("profile", "essential"),
    }


def _organization(db: Session, tenant_id: str) -> Organization:
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise ValueError("Organization not found")
    return org


@router.post("/run")
async def brain_run(
    payload: BrainRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _organization(db, tenant_id)
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
        metadata={"task": payload.task, "commercial_profile": commercial.get("profile", "essential")},
    )
    try:
        result = await LiveIntelligence().run(payload.task, payload.question, messages, payload.preferred_language)
        commit_reservation(
            db,
            reservation,
            event_type="ai_run",
            metadata={
                "status": result.status,
                "task_profile": result.profile,
                "commercial_profile": commercial.get("profile", "essential"),
                "provider_internal": result.provider,
                "model_internal": result.model,
                "response_language": result.response_language,
            },
        )
        db.commit()
    except Exception:
        release_reservation(db, reservation, reason="brain_runtime_exception")
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
        "citations": [citation.model_dump(mode="python") if hasattr(citation, "model_dump") else citation for citation in context.citations[:8]],
        "sample_mode": bool(bundle.get("sample_mode")),
        "preferred_language": payload.preferred_language,
        "response_language": result.response_language,
        "task_profile": result.profile,
        "intelligence_profile": commercial.get("profile", "essential"),
    }


@router.get("/model-smoke")
async def model_smoke(
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org = _organization(db, tenant_id)
    reservation = reserve_quota(db, org, "ai_action", user_id=user.id, metadata={"task": "model_smoke"})
    try:
        result = await LiveIntelligence().run(
            "chat", "Reply with exactly OK.", [{"role": "user", "content": "Reply with exactly OK."}], "en"
        )
        commit_reservation(db, reservation, event_type="ai_run", metadata={"status": result.status, "task": "model_smoke"})
        db.commit()
    except Exception:
        release_reservation(db, reservation, reason="model_smoke_exception")
        db.commit()
        raise
    return {
        "live_model_response": result.status == "ok" and bool(result.content.strip()),
        "task_profile": result.profile,
        "response_language": result.response_language,
    }


from app.api.v1.conversations import router as conversation_history_router  # noqa: E402

router.include_router(conversation_history_router)

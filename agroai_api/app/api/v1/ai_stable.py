from __future__ import annotations

import json
import logging
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
from app.services.gpt56_intelligence import run_gpt56_grounded_intelligence
from app.services.intelligence_context import build_intelligence_context
from app.services.intelligence_grounding import build_intelligence_grounding
from app.services.intelligence_hardening import enrich_grounding_packet, postvalidate_decision, sanitize_customer_answer
from app.services.language import language_matches_target, resolve_language
from app.services.live_intelligence import LiveIntelligence
from app.services.model_router import ModelRouter
from app.services.quota import commit_reservation, release_reservation, reserve_quota
from app.services.resilient_intelligence import run_resilient_intelligence

router = APIRouter(tags=["ai-stable"])
logger = logging.getLogger(__name__)


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


def _grounding_failure_response(payload: BrainRunRequest, bundle: dict[str, Any], task_profile: str) -> dict[str, Any]:
    """Fail closed when the evidence safety boundary cannot be constructed."""
    language = resolve_language(payload.preferred_language, payload.question).response_code
    message = (
        "AGRO-AI cannot produce an operational conclusion because the evidence verification layer is unavailable. "
        "No recommendation or operating number was generated."
    )
    return {
        "status": "unavailable",
        "task": payload.task,
        "model_status": "unavailable",
        "result": {
            "summary": message,
            "answer": message,
            "error": "intelligence_grounding_unavailable",
            "recommendations": [],
            "next_actions": [],
            "risk_flags": ["grounding_verification_unavailable"],
            "customer_safe": True,
        },
        "missing_data": ["Evidence verification layer unavailable"],
        "confidence": "low",
        "citations": [],
        "sample_mode": bool(bundle.get("sample_mode")),
        "preferred_language": payload.preferred_language,
        "response_language": language,
        "task_profile": task_profile,
        "intelligence_profile": (bundle.get("commercial_intelligence") or {}).get("profile", "essential"),
        "reasoning_contract": "evidence_graph_v1_fail_closed",
    }


@router.get("/runtime/ai-router-status")
async def ai_router_status() -> dict[str, Any]:
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
    """Production route: mandatory grounding, then GPT-5.6 or sanitized recovery lane."""
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
    task_profile = LiveIntelligence().profile(payload.task, payload.question)
    reservation = reserve_quota(
        db,
        org,
        "ai_action",
        workspace_id=payload.workspace_id,
        user_id=user.id,
        metadata={"task": payload.task, "route": "resilient_runtime"},
    )

    try:
        packet = build_intelligence_grounding(context, field_id=payload.field_id)
        packet = enrich_grounding_packet(packet, context)
    except Exception as exc:  # noqa: BLE001
        logger.error("intelligence_grounding_failed error=%s", exc.__class__.__name__)
        release_reservation(db, reservation, reason="intelligence_grounding_failed")
        db.commit()
        return _grounding_failure_response(payload, bundle, task_profile)

    try:
        try:
            gpt56 = await run_gpt56_grounded_intelligence(
                question=payload.question,
                task=payload.task,
                profile=task_profile,
                packet=packet,
                conversation_messages=payload.history,
                preferred_language=payload.preferred_language,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("gpt56_grounded inference_failed error=%s", exc.__class__.__name__)
            gpt56 = None

        if gpt56 is not None:
            gpt56.decision = postvalidate_decision(gpt56.decision, packet, question=payload.question)
            response_language = resolve_language(payload.preferred_language, payload.question).response_code
            if language_matches_target(gpt56.decision.answer, response_language):
                body = gpt56.decision.portal_body(packet)
                commit_reservation(
                    db,
                    reservation,
                    event_type="ai_run",
                    metadata={
                        "status": "ok",
                        "task_profile": task_profile,
                        "provider_internal": "openai",
                        "model_internal": gpt56.model,
                        "reasoning_effort_internal": gpt56.reasoning_effort,
                        "route": "resilient_runtime",
                        "grounding_schema": packet.schema_version,
                        "science_ruleset": packet.science_ruleset_version,
                    },
                )
                db.commit()
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
                    "response_language": response_language,
                    "task_profile": task_profile,
                    "intelligence_profile": commercial.get("profile", "essential"),
                    "reasoning_contract": "evidence_graph_v1",
                }
            logger.warning("gpt56_grounded language_mismatch falling_back=true")

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
                "grounding_schema": packet.schema_version,
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

    answer, removed_content = sanitize_customer_answer(result.content.strip(), packet, question=payload.question)
    body = local_plain_body(answer, context, question=payload.question)
    if removed_content:
        body["risk_flags"] = ["unsupported_or_ungrounded_operational_content_removed"]
        body["confidence"] = "low"
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
        "reasoning_contract": "evidence_graph_v1_sanitized_fallback",
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
        try:
            packet = enrich_grounding_packet(build_intelligence_grounding(context, field_id=payload.block_id), context)
            summary, removed = sanitize_customer_answer(str(body.get("summary") or body.get("answer") or ""), packet, question=payload.message)
            if removed:
                body["summary"] = summary
                body["answer"] = summary
                body["risk_flags"] = list(body.get("risk_flags") or []) + ["unsupported_or_ungrounded_operational_content_removed"]
                body["confidence"] = "low"
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_chat safety_guard_failed error=%s", exc.__class__.__name__)
            body = fallback
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

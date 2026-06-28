"""Platform-wide intelligence fabric for AGRO-AI.

This exposes one shared intelligence brief and action endpoint used across
WaterOps, Assurance, Evidence, Reports, Agents, Integrations, and Intelligence.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.api.v1.ai import (
    _deterministic_body,
    _get_evidence_context,
    _run_ai,
    _verification,
)
from app.schemas.ai import IntelligenceRunRequest, IntelligenceRunResponse
from app.services.citation_verifier import verify_citations
from app.services.intelligence_context import build_intelligence_context
from app.services.model_router import ModelRouter


router = APIRouter(prefix="/intelligence", tags=["platform-intelligence"])


SupportedAction = Literal[
    "field_diagnosis",
    "irrigation_plan",
    "assurance_packet",
    "evidence_gap_analysis",
    "integration_diagnosis",
    "report_draft",
]


class IntelligenceActionRequest(BaseModel):
    action: SupportedAction
    payload: dict[str, Any] = Field(default_factory=dict)


ACTION_TASK_MAP: dict[str, str] = {
    "field_diagnosis": "chat",
    "irrigation_plan": "irrigation_recommendation",
    "assurance_packet": "assurance_review",
    "evidence_gap_analysis": "gap_analysis",
    "integration_diagnosis": "integration_diagnosis",
    "report_draft": "report_draft",
}

RUN_TASK_MAP: dict[str, str] = {
    "chat": "chat",
    "field_diagnosis": "irrigation_recommendation",
    "exception_triage": "gap_analysis",
    "decision_workbench": "irrigation_recommendation",
    "report_factory": "report_draft",
    "connector_diagnosis": "integration_diagnosis",
    "readiness_analysis": "assurance_review",
}


def _items(context: Any, item_type: str) -> list[dict[str, Any]]:
    return [item for item in context.evidence if item.get("type") == item_type]


def _first(context: Any, item_type: str) -> dict[str, Any]:
    rows = _items(context, item_type)
    return rows[0] if rows else {}


def _mode(context: Any) -> str:
    evidence_text = str(context.evidence).lower()
    if "evaluation_sample" in evidence_text:
        return "evaluation"
    if context.missing_data:
        return "evaluation"
    return "live"


def _integration_status(context: Any) -> list[dict[str, Any]]:
    readiness = _first(context, "integration_readiness")
    items = readiness.get("items") or []
    if items:
        return items

    return [
        {
            "name": "WiseConn",
            "status": "missing_credentials",
            "next_step": "Add WiseConn credentials or upload WiseConn exports.",
            "expected_data": ["zones", "controller events", "irrigation history", "flow"],
        },
        {
            "name": "Talgil",
            "status": "missing_credentials",
            "next_step": "Add Talgil credentials or upload controller exports.",
            "expected_data": ["targets", "program state", "valve state", "irrigation events"],
        },
        {
            "name": "Manual/CSV evidence",
            "status": "available",
            "next_step": "Upload ET, soil, irrigation, flow, and field records.",
            "expected_data": ["CSV", "PDF", "operator notes", "field logs"],
        },
        {
            "name": "Weather/public data",
            "status": "not_configured",
            "next_step": "Configure weather/OpenET/public source before live recommendations.",
            "expected_data": ["ET0", "temperature", "precipitation", "forecast"],
        },
    ]


def _brief_from_context(context: Any) -> dict[str, Any]:
    workspace = _first(context, "workspace")
    block = _first(context, "block")
    telemetry = _first(context, "telemetry_recent")
    recommendation = _first(context, "recommendation_recent")

    records = telemetry.get("records") or []
    by_type: dict[str, int] = {}
    latest_at = None

    for row in records:
        kind = str(row.get("type") or "unknown")
        by_type[kind] = by_type.get(kind, 0) + 1
        ts = row.get("timestamp")
        if ts and (latest_at is None or str(ts) > str(latest_at)):
            latest_at = str(ts)

    allocated = float(block.get("water_budget_allocated") or 0)
    used = float(block.get("water_budget_used") or 0)
    used_pct = round((used / allocated) * 100, 1) if allocated else None
    remaining = round(allocated - used, 2) if allocated else None

    risks: list[str] = []
    if _mode(context) == "evaluation":
        risks.append("Evaluation sample is available, but it is not live operational data.")
    if any("live WiseConn" in item for item in context.missing_data):
        risks.append("WiseConn is not connected. Controller evidence is missing.")
    if any("live Talgil" in item for item in context.missing_data):
        risks.append("Talgil is not connected. Controller evidence is missing.")
    if not records:
        risks.append("No recent telemetry records are available.")
    if used_pct is not None and used_pct >= 70:
        risks.append("Water budget use is elevated and should be reviewed before the next irrigation decision.")

    recommendations: list[dict[str, Any]] = []
    if recommendation:
        recommendations.append(
            {
                "type": "irrigation",
                "when": recommendation.get("when"),
                "duration_min": recommendation.get("duration_min"),
                "volume_m3": recommendation.get("volume_m3"),
                "confidence": recommendation.get("confidence"),
                "explanations": recommendation.get("explanations") or [],
                "source": (recommendation.get("meta_data") or {}).get("source", "recommendation_record"),
                "operational_use": (recommendation.get("meta_data") or {}).get("operational_use", False),
            }
        )

    next_actions = [
        {
            "id": "connect_source",
            "label": "Connect WiseConn or Talgil credentials",
            "priority": "high",
        },
        {
            "id": "upload_recent_telemetry",
            "label": "Upload recent ET, flow, soil moisture, and irrigation records",
            "priority": "high",
        },
        {
            "id": "run_assurance_review",
            "label": "Run assurance review after live data is connected",
            "priority": "medium",
        },
        {
            "id": "draft_report",
            "label": "Draft an evidence-backed field report",
            "priority": "medium",
        },
    ]

    citations = [
        citation.model_dump(mode="python") if hasattr(citation, "model_dump") else citation
        for citation in context.citations
    ]

    evidence_count = len(context.evidence)
    citation_count = len(citations)
    telemetry_count = len(records)
    assurance_score = min(
        95,
        35
        + min(telemetry_count, 10) * 3
        + citation_count * 10
        + (15 if recommendation else 0)
        + (10 if block else 0),
    )

    return {
        "status": "ok",
        "mode": _mode(context),
        "workspace": {
            "id": context.workspace_id,
            "name": workspace.get("name"),
            "crop": workspace.get("crop"),
            "region": workspace.get("region") or context.region,
            "mode": workspace.get("mode"),
            "source": workspace.get("source", "saas_workspace") if workspace else None,
        },
        "field_state": {
            "block_id": context.block_id,
            "name": block.get("name"),
            "crop_type": block.get("crop_type") or context.crop_type,
            "soil_type": block.get("soil_type"),
            "area_ha": block.get("area_ha"),
            "source": block.get("source"),
            "sample_notice": ((block.get("config") or {}).get("sample_notice") if block else None),
        },
        "water_status": {
            "allocated_m3": allocated or None,
            "used_m3": used or None,
            "remaining_m3": remaining,
            "used_pct": used_pct,
            "status": "watch" if used_pct is not None and used_pct >= 70 else "normal",
            "source": block.get("source") if block else None,
        },
        "telemetry_status": {
            "record_count": telemetry_count,
            "latest_at": latest_at,
            "by_type": by_type,
            "quality": "sample_ready" if telemetry_count else "missing",
            "source_mode": _mode(context),
        },
        "integration_status": _integration_status(context),
        "assurance_status": {
            "score": assurance_score,
            "status": "evaluation_ready" if evidence_count else "missing_evidence",
            "evidence_count": evidence_count,
            "citation_count": citation_count,
            "live_certification": False,
            "reviewer_note": (
                "Evaluation-ready only. Live assurance requires connected controller/sensor evidence."
                if _mode(context) == "evaluation"
                else "Live evidence available for review."
            ),
        },
        "recommendations": recommendations,
        "risks": risks,
        "missing_data": context.missing_data,
        "next_actions": next_actions,
        "citations": citations,
    }


def _result_payload(task: str, question: str, body: dict[str, Any], context_bundle: dict[str, Any], model_status: str, provider: str, model: str | None) -> dict[str, Any]:
    context = context_bundle["evidence_context"]
    readiness = context_bundle.get("readiness") or {}
    fields = context_bundle.get("fields") or {}
    exceptions_payload = context_bundle.get("exceptions") or {}

    if task == "decision_workbench":
        return {
            "summary": body.get("recommendation") or body.get("summary") or "Collect missing data first before approving an operating decision.",
            "recommendation": body.get("recommendation") or body.get("summary"),
            "why": body.get("why") or body.get("summary"),
            "evidence_used": body.get("evidence_used") or body.get("available_data") or [],
            "missing_evidence": body.get("missing_data") or context.missing_data,
            "operator_instructions": body.get("next_actions") or body.get("recommendations") or [],
            "risk_flags": body.get("risk_flags") or body.get("risks") or [],
            "confidence": body.get("confidence") or "low",
            "model_status": model_status,
            "provider": provider,
            "model": model,
        }

    if task == "report_factory":
        return {
            "title": body.get("title") or "AGRO-AI operating report",
            "executive_summary": body.get("summary") or "Evidence-backed report draft generated.",
            "key_findings": body.get("sections") or body.get("available_data") or [],
            "missing_evidence": body.get("missing_data") or context.missing_data,
            "recommended_next_actions": body.get("next_actions") or body.get("recommendations") or [],
            "reviewer_notes": body.get("reviewer_notes") or body.get("risk_flags") or [],
            "confidence": body.get("confidence") or "low",
            "model_status": model_status,
            "provider": provider,
            "model": model,
        }

    if task == "connector_diagnosis":
        return {
            "summary": body.get("summary") or "Connector readiness diagnosis generated.",
            "connected_integrations": [
                row.get("name")
                for row in _integration_status(context)
                if row.get("status") in {"connected", "ready", "available", "synced"}
            ],
            "available_sample_data": body.get("available_data") or readiness.get("present_source_types") or [],
            "missing_credentials": [
                row.get("name")
                for row in _integration_status(context)
                if row.get("status") in {"missing_credentials", "not_configured", "setup_required"}
            ],
            "next_steps_to_go_live": body.get("next_actions") or body.get("recommendations") or [],
            "confidence": body.get("confidence") or "low",
            "model_status": model_status,
            "provider": provider,
            "model": model,
        }

    return {
        "summary": body.get("summary") or body.get("answer") or f"AGRO-AI completed {task}.",
        "question": question,
        "available_data": body.get("available_data") or body.get("evidence_used") or [],
        "missing_data": body.get("missing_data") or context.missing_data,
        "recommendations": body.get("recommendations") or body.get("next_actions") or [],
        "risk_flags": body.get("risk_flags") or body.get("risks") or [],
        "readiness_level": readiness.get("readiness_level"),
        "field_count": len((fields.get("fields") or [])) if isinstance(fields, dict) else 0,
        "exception_count": len((exceptions_payload.get("exceptions") or [])) if isinstance(exceptions_payload, dict) else 0,
        "confidence": body.get("confidence") or "low",
        "model_status": model_status,
        "provider": provider,
        "model": model,
    }


@router.get("/brief")
async def intelligence_brief(
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = _get_evidence_context(db=db, tenant_id=tenant_id)
    return _brief_from_context(context)


@router.post("/action")
async def intelligence_action(
    payload: IntelligenceActionRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = _get_evidence_context(db=db, tenant_id=tenant_id)
    task = ACTION_TASK_MAP.get(payload.action)

    if not task:
        raise HTTPException(status_code=400, detail="Unsupported intelligence action")

    instruction = (
        f"Run platform-wide AGRO-AI action: {payload.action}. "
        f"Inputs: {payload.payload}. "
        "Return customer-safe JSON with findings, recommendations, missing_data, next_actions, citations, and confidence."
    )

    body, result = await _run_ai(
        task=task,
        user_instruction=instruction,
        context=context,
    )

    if not isinstance(body, dict):
        body = _deterministic_body(context)

    summary = str(
        body.get("summary")
        or body.get("recommendation")
        or body.get("proof_summary")
        or body.get("readiness_status")
        or "AGRO-AI generated an evidence-grounded action result."
    )

    findings = (
        body.get("findings")
        or body.get("available_data")
        or body.get("evidence_used")
        or body.get("readiness_gaps")
        or body.get("observed_signals")
        or []
    )

    recommendations = body.get("recommendations") or body.get("next_action") or []
    if isinstance(recommendations, str):
        recommendations = [recommendations]

    next_actions = body.get("next_actions") or body.get("next_action") or []
    if isinstance(next_actions, str):
        next_actions = [next_actions]

    citations = [
        citation.model_dump(mode="python") if hasattr(citation, "model_dump") else citation
        for citation in context.citations
    ]

    return {
        "status": "completed" if result.status == "ok" else "unavailable",
        "action": payload.action,
        "summary": summary,
        "findings": findings,
        "recommendations": recommendations,
        "missing_data": body.get("missing_data") or context.missing_data,
        "next_actions": next_actions,
        "citations": citations,
        "verification": _verification(result.status, context).model_dump(mode="python"),
        "provider": result.provider,
        "model": result.model,
        "demo_fallback": result.demo_fallback,
        "raw": body,
    }


@router.post("/run", response_model=IntelligenceRunResponse)
async def intelligence_run(
    payload: IntelligenceRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IntelligenceRunResponse:
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

    context = context_bundle["evidence_context"]
    mapped_task = RUN_TASK_MAP.get(payload.task, "chat")
    instruction = payload.question
    if payload.audience:
        instruction = f"Audience: {payload.audience}. {instruction}"

    body, result = await _run_ai(
        task=mapped_task,
        user_instruction=instruction,
        context=context,
    )

    model_router = ModelRouter()
    model_status = "live" if result.status == "ok" and not result.demo_fallback else "fallback"
    if not model_router.status()["configured"]:
        model_status = "fallback" if result.demo_fallback else "unavailable"

    result_payload = _result_payload(payload.task, payload.question, body, context_bundle, model_status, result.provider, result.model)
    verification, result_payload = verify_citations(
        citations=context.citations,
        result=result_payload,
        tenant_id=tenant_id,
        workspace_id=context.workspace_id,
    )

    return IntelligenceRunResponse(
        status="completed" if result.status == "ok" else "unavailable",
        task=payload.task,
        model=result.model,
        model_status=model_status if result.status == "ok" or result.demo_fallback else "unavailable",
        provider=result.provider,
        result=result_payload,
        citations=verification.citations,
        verification=verification,
        missing_data=result_payload.get("missing_data") or context.missing_data,
        confidence=str(result_payload.get("confidence") or "low"),
    )

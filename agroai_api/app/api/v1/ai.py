"""Tenant-scoped AGRO-AI Intelligence Engine routes."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.block import Block
from app.models.recommendation import Recommendation
from app.models.saas import Organization, Workspace
from app.models.telemetry import Telemetry
from app.schemas.ai import (
    AIStatusResponse,
    AgentRunRequest,
    AgentRunResponse,
    ChatRequest,
    ChatResponse,
    EvidenceContext,
    ToolCitation,
    VerificationResult,
)
from app.services.ai_gateway import AIGateway, parse_model_json
from app.services.model_router import ModelRouter
from app.services.evaluation_seed import ensure_evaluation_context

router = APIRouter(tags=["ai"])


SYSTEM_PROMPT = """You are AGRO-AI, an agriculture intelligence engine.

Return valid JSON only. Never include chain-of-thought, scratchpad, <think>, markdown fences, or hidden reasoning.

Use this JSON shape:
{
  "summary": "...",
  "available_data": [],
  "missing_data": [],
  "integration_status": [],
  "recommendations": [],
  "next_actions": [],
  "confidence": "low|medium|high",
  "customer_safe": true
}

Rules:
- Do not invent sensor data, integrations, compliance status, prices, or yields.
- Use only the provided tenant-scoped evidence.
- If evidence is evaluation_sample, label it as evaluation_sample.
- Never claim WiseConn, Talgil, weather, OpenET, or controller data is live unless the evidence says connected/live.
- If context is incomplete, still provide a useful operational diagnosis.
- Keep output executive-readable, practical, and agriculture-specific.
"""


TASK_PROMPTS: dict[str, str] = {
    "chat": "Answer the operator's question using only the evidence context.",
    "irrigation_recommendation": (
        "Return JSON with recommendation, confidence, evidence_used, missing_data, "
        "risk_flags, and next_action for irrigation operations."
    ),
    "assurance_review": (
        "Return JSON with readiness_gaps, blocker_severity, evidence_needed, "
        "reviewer_safe_language, and next_action."
    ),
    "report_draft": (
        "Draft structured report sections using only available data. Return JSON "
        "with title, sections, citations, missing_data, and reviewer_notes."
    ),
    "integration_diagnosis": (
        "Diagnose integration readiness. Return JSON with status, observed_signals, "
        "missing_integrations, risks, and next_action."
    ),
    "gap_analysis": (
        "Return JSON with readiness_gaps, severity, evidence_needed, and next_action."
    ),
    "proof_draft": (
        "Return JSON with proof_summary, evidence_used, reviewer_safe_language, "
        "missing_data, and next_action."
    ),
    "readiness_refresh": (
        "Return JSON with readiness_status, blockers, evidence_to_refresh, "
        "risk_flags, and next_action."
    ),
}

TASK_PROFILE_MAP = {
    "chat": "chat",
    "irrigation_recommendation": "field_diagnosis",
    "assurance_review": "readiness_analysis",
    "report_draft": "report_factory",
    "integration_diagnosis": "connector_diagnosis",
    "gap_analysis": "readiness_analysis",
    "proof_draft": "report_factory",
    "readiness_refresh": "readiness_analysis",
}


def _integration_status() -> list[dict[str, str]]:
    return [
        {
            "name": "WiseConn",
            "status": "missing_credentials",
            "next_step": "Add WiseConn API credentials or upload WiseConn exports.",
        },
        {
            "name": "Talgil",
            "status": "missing_credentials",
            "next_step": "Add Talgil API credentials or upload controller exports.",
        },
        {
            "name": "Manual/CSV evidence",
            "status": "available",
            "next_step": "Upload recent irrigation, ET, flow, soil, and field records.",
        },
        {
            "name": "Weather/public data",
            "status": "not_configured",
            "next_step": "Configure weather/public data source before live recommendations.",
        },
    ]


def _get_workspace(db: Session, tenant_id: str, workspace_id: str | None) -> Workspace | None:
    if workspace_id:
        workspace = db.get(Workspace, workspace_id)
        if workspace and workspace.organization_id == tenant_id:
            return workspace
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return (
        db.query(Workspace)
        .filter(Workspace.organization_id == tenant_id)
        .order_by(Workspace.created_at.asc())
        .first()
    )


def _get_evidence_context(
    *,
    db: Session,
    tenant_id: str,
    block_id: str | None = None,
    workspace_id: str | None = None,
) -> EvidenceContext:
    org = db.get(Organization, tenant_id)
    workspace = _get_workspace(db, tenant_id, workspace_id)

    # Repair existing orgs that registered before evaluation context existed.
    if org:
        ids = ensure_evaluation_context(db, org, workspace)
        db.commit()
        workspace = _get_workspace(db, tenant_id, workspace_id or ids.get("workspace_id"))

    evidence: list[dict[str, Any]] = []
    citations: list[ToolCitation] = []
    missing: list[str] = []
    block: Block | None = None

    if block_id:
        block = db.query(Block).filter(
            and_(Block.id == block_id, Block.tenant_id == tenant_id)
        ).first()
        if not block:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace evidence not found",
            )
    else:
        block = db.query(Block).filter(Block.tenant_id == tenant_id).first()

    if workspace:
        evidence.append(
            {
                "type": "workspace",
                "id": workspace.id,
                "name": workspace.name,
                "crop": workspace.crop,
                "region": workspace.region,
                "mode": workspace.mode,
                "source": "saas_workspace",
            }
        )
        citations.append(
            ToolCitation(
                source_type="workspace",
                source_id=workspace.id,
                title=f"Workspace {workspace.name}",
                tenant_id=tenant_id,
                workspace_id=workspace.id,
                fields=["name", "crop", "region", "mode"],
            )
        )
    else:
        missing.append("workspace record")

    evidence.append(
        {
            "type": "integration_readiness",
            "source": "system_status",
            "items": _integration_status(),
        }
    )

    if block:
        evidence.append(
            {
                "type": "block",
                "id": block.id,
                "name": block.name,
                "area_ha": block.area_ha,
                "crop_type": block.crop_type,
                "soil_type": block.soil_type,
                "water_budget_allocated": block.water_budget_allocated,
                "water_budget_used": block.water_budget_used,
                "source": (block.config or {}).get("source", "field_record"),
                "config": block.config or {},
            }
        )
        citations.append(
            ToolCitation(
                source_type="block",
                source_id=block.id,
                title=f"Block {block.name}",
                tenant_id=tenant_id,
                workspace_id=workspace.id if workspace else workspace_id,
                fields=[
                    "crop_type",
                    "soil_type",
                    "area_ha",
                    "water_budget_allocated",
                    "water_budget_used",
                ],
            )
        )

        since = datetime.utcnow() - timedelta(days=14)
        telemetry = db.query(Telemetry).filter(
            and_(
                Telemetry.tenant_id == tenant_id,
                Telemetry.block_id == block.id,
                Telemetry.timestamp >= since,
            )
        ).order_by(Telemetry.timestamp.desc()).limit(20).all()
        if telemetry:
            evidence.append(
                {
                    "type": "telemetry_recent",
                    "records": [
                        {
                            "id": row.id,
                            "type": row.type,
                            "timestamp": row.timestamp.isoformat(),
                            "value": row.value,
                            "unit": row.unit,
                            "source": row.source,
                            "meta_data": row.meta_data or {},
                        }
                        for row in telemetry
                    ],
                }
            )
            citations.append(
                ToolCitation(
                    source_type="telemetry",
                    source_id=block.id,
                    title="Recent telemetry records",
                    tenant_id=tenant_id,
                    workspace_id=workspace.id if workspace else workspace_id,
                    fields=["type", "timestamp", "value", "unit", "source"],
                    trace={"record_count": len(telemetry)},
                )
            )
        else:
            missing.append("recent telemetry for the selected block")

        recommendation = db.query(Recommendation).filter(
            and_(Recommendation.tenant_id == tenant_id, Recommendation.block_id == block.id)
        ).order_by(Recommendation.created_at.desc()).first()
        if recommendation:
            evidence.append(
                {
                    "type": "recommendation_recent",
                    "id": recommendation.id,
                    "when": recommendation.when.isoformat(),
                    "duration_min": recommendation.duration_min,
                    "volume_m3": recommendation.volume_m3,
                    "confidence": recommendation.confidence,
                    "explanations": recommendation.explanations or [],
                    "version": recommendation.version,
                    "meta_data": recommendation.meta_data or {},
                }
            )
            citations.append(
                ToolCitation(
                    source_type="recommendation",
                    source_id=recommendation.id,
                    title="Most recent irrigation recommendation",
                    tenant_id=tenant_id,
                    workspace_id=workspace.id if workspace else workspace_id,
                    fields=["when", "duration_min", "volume_m3", "confidence"],
                )
            )
        else:
            missing.append("recent irrigation recommendation for the selected block")
    else:
        missing.extend(["workspace/block record", "recent telemetry", "recent recommendation"])

    live_missing = ["live WiseConn credentials", "live Talgil credentials", "confirmed live telemetry stream"]
    for item in live_missing:
        if item not in missing:
            missing.append(item)

    return EvidenceContext(
        organization_id=tenant_id,
        workspace_id=workspace.id if workspace else workspace_id,
        block_id=block.id if block else block_id,
        crop_type=block.crop_type if block else (workspace.crop if workspace else None),
        region=workspace.region if workspace else None,
        evidence=evidence,
        missing_data=missing,
        citations=citations,
    )


def _verification(status_value: str, context: EvidenceContext) -> VerificationResult:
    status_name = "verified" if status_value == "ok" and not context.missing_data else "partial"
    if status_value != "ok":
        status_name = "unavailable"
    return VerificationResult(
        status=status_name,
        missing_data=context.missing_data,
        risk_flags=[] if status_value == "ok" else ["AI provider unavailable; deterministic fallback used."],
        citations=context.citations,
    )


def _deterministic_body(context: EvidenceContext) -> dict[str, Any]:
    available: list[str] = []
    for item in context.evidence:
        item_type = item.get("type", "evidence")
        source = item.get("source")
        label = f"{item_type}" + (f" ({source})" if source else "")
        available.append(label)

    return {
        "summary": (
            "AGRO-AI can authenticate this organization and inspect its evaluation workspace. "
            "Starter field context is available, but live controller and sensor integrations are not connected yet."
        ),
        "available_data": available,
        "missing_data": context.missing_data,
        "integration_status": _integration_status(),
        "recommendations": [
            "Use the evaluation sample only for product walkthrough and QA.",
            "Connect WiseConn or Talgil credentials, or upload recent controller exports.",
            "Confirm crop, acreage, soil type, water budget, and recent irrigation history before operational recommendations.",
            "Run an assurance review after live telemetry is connected.",
        ],
        "next_actions": [
            "connect_source",
            "upload_recent_telemetry",
            "confirm_field_profile",
            "run_assurance_review",
        ],
        "confidence": "low",
        "customer_safe": True,
    }


def _weak_or_empty(body: dict[str, Any]) -> bool:
    # Different structured routes intentionally return different primary keys.
    # Do not throw away valid model JSON just because it uses recommendation,
    # proof_summary, readiness_status, findings, title, or sections instead of
    # summary/answer.
    primary = str(
        body.get("summary")
        or body.get("answer")
        or body.get("recommendation")
        or body.get("proof_summary")
        or body.get("readiness_status")
        or body.get("findings")
        or body.get("title")
        or body.get("sections")
        or ""
    ).strip().lower()

    if not primary:
        return True

    bad = [
        "reasoning-only",
        "no customer-safe answer",
        "ai provider returned no customer-safe final answer",
        "<think>",
        "okay, so i'm",
        "i'm trying to figure",
    ]
    return any(marker in primary for marker in bad)


async def _run_ai(
    *,
    task: str,
    user_instruction: str,
    context: EvidenceContext,
    temperature: float = 0.2,
) -> tuple[dict[str, Any], Any]:
    router = ModelRouter()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Task: {TASK_PROMPTS[task]}\n"
                f"User instruction: {user_instruction}\n"
                f"Evidence context JSON: {context.model_dump_json()}"
            ),
        },
    ]
    result, _selection = await router.run(
        task=TASK_PROFILE_MAP.get(task, "chat"),
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    body = parse_model_json(result.content)
    if result.status != "ok" or _weak_or_empty(body):
        body = _deterministic_body(context)
    return body, result


@router.get("/ai/status", response_model=AIStatusResponse)
async def ai_status() -> AIStatusResponse:
    model_router = ModelRouter()
    return AIStatusResponse(**model_router.status())


@router.get("/ai/context", response_model=EvidenceContext)
async def ai_context(
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> EvidenceContext:
    return _get_evidence_context(db=db, tenant_id=tenant_id)


@router.post("/ai/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> ChatResponse:
    context = _get_evidence_context(
        db=db,
        tenant_id=tenant_id,
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
    )
    body, result = await _run_ai(
        task="chat",
        user_instruction=payload.message,
        context=context,
        temperature=payload.temperature,
    )
    output = body.get("summary") or body.get("answer") or result.content
    return ChatResponse(
        status="ok" if result.status == "ok" else "unavailable",
        output=str(output),
        provider=result.provider,
        model=result.model,
        demo_fallback=result.demo_fallback,
        evidence_context=context,
        citations=context.citations,
        verification=_verification(result.status, context),
        raw=body,
    )


async def _structured_endpoint(
    *,
    task: str,
    instruction: str,
    block_id: str | None,
    workspace_id: str | None,
    tenant_id: str,
    db: Session,
) -> AgentRunResponse:
    context = _get_evidence_context(
        db=db,
        tenant_id=tenant_id,
        block_id=block_id,
        workspace_id=workspace_id,
    )
    body, result = await _run_ai(task=task, user_instruction=instruction, context=context)
    return AgentRunResponse(
        status="completed" if result.status == "ok" else "unavailable",
        task=task,
        output=body,
        provider=result.provider,
        model=result.model,
        evidence_context=context,
        citations=context.citations,
        verification=_verification(result.status, context),
        demo_fallback=result.demo_fallback,
    )


@router.post("/ai/irrigation-recommendation", response_model=AgentRunResponse)
async def irrigation_recommendation(
    payload: AgentRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    return await _structured_endpoint(
        task="irrigation_recommendation",
        instruction=str(payload.inputs or {}),
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
        tenant_id=tenant_id,
        db=db,
    )


@router.post("/ai/assurance-review", response_model=AgentRunResponse)
async def assurance_review(
    payload: AgentRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    return await _structured_endpoint(
        task="assurance_review",
        instruction=str(payload.inputs or {}),
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
        tenant_id=tenant_id,
        db=db,
    )


@router.post("/ai/report-draft", response_model=AgentRunResponse)
async def report_draft(
    payload: AgentRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    return await _structured_endpoint(
        task="report_draft",
        instruction=str(payload.inputs or {}),
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
        tenant_id=tenant_id,
        db=db,
    )


@router.post("/ai/integration-diagnosis", response_model=AgentRunResponse)
async def integration_diagnosis(
    payload: AgentRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    return await _structured_endpoint(
        task="integration_diagnosis",
        instruction=str(payload.inputs or {}),
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
        tenant_id=tenant_id,
        db=db,
    )


@router.post("/agents/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    return await _structured_endpoint(
        task=payload.task,
        instruction=str(payload.inputs or {}),
        block_id=payload.block_id,
        workspace_id=payload.workspace_id,
        tenant_id=tenant_id,
        db=db,
    )

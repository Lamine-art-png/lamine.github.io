"""Tenant-scoped AGRO-AI Intelligence Engine routes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.api.v1.brain import compact_local_messages, is_local_ai, local_plain_body
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
from app.services.ai_gateway import parse_model_json
from app.services.evaluation_seed import ensure_evaluation_context
from app.services.model_router import ModelRouter

router = APIRouter(tags=["ai"])


SYSTEM_PROMPT = """You are AGRO-AI, the enterprise agriculture operating intelligence layer.

You are not a generic chatbot and you are not a static status generator. You are an operating agent for farms, water agencies, agronomists, advisors, exporters, lenders, insurers, and agriculture enterprise teams.

AGRO-AI / Terris job:
- ingest scattered agriculture evidence and machine data;
- preserve source provenance;
- reason over water, irrigation, compliance, field operations, telemetry, uploaded files, reports, and connector status;
- produce decisions, field work, evidence gaps, report drafts, operating checklists, and next actions.

Return valid JSON only. Never include chain-of-thought, scratchpad, <think>, markdown fences, or hidden reasoning.

Use this customer-safe JSON shape:
{
  "summary": "natural direct answer to the user's actual request",
  "answer": "same answer, written naturally if useful",
  "work_completed": [],
  "available_data": [],
  "missing_data": [],
  "agent_plan": [],
  "recommendations": [],
  "next_actions": [],
  "risk_flags": [],
  "confidence": "low|medium|high",
  "customer_safe": true
}

Operating rules:
- Answer the user's actual question first, naturally and specifically.
- Do not repeat the same template. Vary the response based on the request and evidence.
- Use only tenant-scoped evidence provided in the context. Do not invent live telemetry, connected integrations, yields, compliance status, savings, prices, customer facts, or sensor values.
- Distinguish measured, uploaded, reported, inferred, sample, stale, missing, and live evidence.
- If evidence is incomplete, do not stop. Say what can be done now, what cannot be trusted yet, and what evidence is needed next.
- Keep debug/provider/runtime language out of the customer answer.
"""

PLANNER_PROMPT = """You are the AGRO-AI planning layer. Build a short execution plan before final response.

Return JSON only:
{
  "intent": "irrigation|compliance|integration|field_ops|data_work|reporting|general",
  "user_goal": "what the user wants",
  "evidence_to_inspect": [],
  "operations_to_run": [],
  "answer_strategy": [],
  "do_not_claim": []
}

Do not answer the customer yet. Decide what kind of work AGRO-AI should perform with the available tenant evidence.
"""

FINAL_AGENT_PROMPT = """Now produce the final AGRO-AI answer as a customer-safe operating agent.

Use the plan, tenant evidence, and user request. Be natural and direct, not mechanical. If the requested work requires live connectors or files that are not present, be clear and produce the exact next operating steps instead of pretending.

Return valid JSON only using the required shape.
"""

TASK_PROMPTS: dict[str, str] = {
    "chat": (
        "Act as the AGRO-AI operating agent. Answer naturally, then produce concrete work completed, evidence used, missing evidence, an operating plan, next actions, and risks."
    ),
    "irrigation_recommendation": (
        "Prepare an irrigation operating recommendation. Return recommendation, evidence_used, missing_data, risk_flags, operator checklist, and next_action."
    ),
    "assurance_review": (
        "Run an assurance review. Return readiness_gaps, blocker_severity, evidence_needed, reviewer-safe language, and next_action."
    ),
    "report_draft": (
        "Draft an owner-ready report from available evidence. Return title, sections, citations, missing_data, reviewer_notes, and next_action."
    ),
    "integration_diagnosis": (
        "Diagnose integration readiness. Return connected or missing systems, observed_signals, risks, setup blockers, and next_action."
    ),
    "gap_analysis": (
        "Find evidence and operating gaps. Return readiness_gaps, severity, evidence_needed, owner impact, and next_action."
    ),
    "proof_draft": (
        "Prepare an evidence-backed proof draft. Return proof_summary, evidence_used, reviewer-safe language, missing_data, and next_action."
    ),
    "readiness_refresh": (
        "Refresh operating readiness. Return readiness_status, blockers, evidence_to_refresh, risk_flags, and next_action."
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
        {"name": "WiseConn", "status": "missing_credentials", "next_step": "Add WiseConn API credentials or upload WiseConn exports."},
        {"name": "Talgil", "status": "missing_credentials", "next_step": "Add Talgil API credentials or upload controller exports."},
        {"name": "Manual/CSV evidence", "status": "available", "next_step": "Upload recent irrigation, ET, flow, soil, and field records."},
        {"name": "Weather/public data", "status": "not_configured", "next_step": "Configure weather/public data source before live recommendations."},
    ]


def _get_workspace(db: Session, tenant_id: str, workspace_id: str | None) -> Workspace | None:
    if workspace_id:
        workspace = db.get(Workspace, workspace_id)
        if workspace and workspace.organization_id == tenant_id:
            return workspace
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return db.query(Workspace).filter(Workspace.organization_id == tenant_id).order_by(Workspace.created_at.asc()).first()


def _get_evidence_context(*, db: Session, tenant_id: str, block_id: str | None = None, workspace_id: str | None = None) -> EvidenceContext:
    org = db.get(Organization, tenant_id)
    workspace = _get_workspace(db, tenant_id, workspace_id)

    if org:
        ids = ensure_evaluation_context(db, org, workspace)
        db.commit()
        workspace = _get_workspace(db, tenant_id, workspace_id or ids.get("workspace_id"))

    evidence: list[dict[str, Any]] = []
    citations: list[ToolCitation] = []
    missing: list[str] = []
    block: Block | None = None

    if block_id:
        block = db.query(Block).filter(and_(Block.id == block_id, Block.tenant_id == tenant_id)).first()
        if not block:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace evidence not found")
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

    evidence.append({"type": "integration_readiness", "source": "system_status", "items": _integration_status()})

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
                fields=["crop_type", "soil_type", "area_ha", "water_budget_allocated", "water_budget_used"],
            )
        )

        since = datetime.utcnow() - timedelta(days=14)
        telemetry = (
            db.query(Telemetry)
            .filter(and_(Telemetry.tenant_id == tenant_id, Telemetry.block_id == block.id, Telemetry.timestamp >= since))
            .order_by(Telemetry.timestamp.desc())
            .limit(20)
            .all()
        )
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

        recommendation = (
            db.query(Recommendation)
            .filter(and_(Recommendation.tenant_id == tenant_id, Recommendation.block_id == block.id))
            .order_by(Recommendation.created_at.desc())
            .first()
        )
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

    for item in ["live WiseConn credentials", "live Talgil credentials", "confirmed live telemetry stream"]:
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


def _evidence_label(item: dict[str, Any]) -> str:
    item_type = item.get("type", "evidence")
    if item_type == "workspace":
        details = [item.get("name"), item.get("crop"), item.get("region")]
        return "Workspace profile" + (f" — {', '.join(str(x) for x in details if x)}" if any(details) else "")
    if item_type == "block":
        details = [item.get("name"), item.get("crop_type"), item.get("soil_type")]
        return "Field/block profile" + (f" — {', '.join(str(x) for x in details if x)}" if any(details) else "")
    if item_type == "telemetry_recent":
        return f"Recent telemetry records — {len(item.get('records') or [])} rows"
    if item_type == "recommendation_recent":
        return "Most recent irrigation recommendation"
    if item_type == "integration_readiness":
        return "Integration readiness map"
    source = item.get("source")
    return f"{item_type}" + (f" ({source})" if source else "")


def _question_intent(user_instruction: str, task: str) -> str:
    text = f"{task} {user_instruction}".lower()
    checks = [
        ("irrigation", ["irrigation", "water", "et", "soil", "moisture", "valve", "flow", "schedule"]),
        ("compliance", ["compliance", "report", "audit", "assurance", "evidence", "packet", "agency", "nrds", "water use"]),
        ("integration", ["integrat", "connector", "wiseconn", "talgil", "john deere", "deere", "api", "upload", "source"]),
        ("field_ops", ["task", "operator", "field", "exception", "priority", "checklist", "work order", "decision"]),
        ("data_work", ["data", "csv", "pdf", "scattered", "organize", "analyze", "dataset", "documents"]),
    ]
    for intent, keywords in checks:
        if any(keyword in text for keyword in keywords):
            return intent
    return "general"


def _deterministic_body(context: EvidenceContext, *, user_instruction: str = "", task: str = "chat") -> dict[str, Any]:
    available = [_evidence_label(item) for item in context.evidence]
    missing = list(dict.fromkeys(context.missing_data))
    intent = _question_intent(user_instruction, task)
    workspace_phrase = "this workspace"
    workspace = next((item for item in context.evidence if item.get("type") == "workspace"), None)
    if workspace and workspace.get("name"):
        workspace_phrase = f"the {workspace.get('name')} workspace"

    intent_summaries = {
        "irrigation": f"For irrigation work in {workspace_phrase}, I can organize the current field profile and evidence trail, but I would not approve a live irrigation recommendation until controller, flow, ET/weather, and recent field telemetry are connected or uploaded.",
        "compliance": f"For compliance or assurance work in {workspace_phrase}, I can start assembling the evidence map now. The blocker is not the report format; it is missing live, traceable records that prove water use, field activity, and source provenance.",
        "integration": f"For integration work in {workspace_phrase}, the next move is to turn each source into a verified data lane: credentials or exports, normalized records, freshness checks, and evidence citations.",
        "field_ops": f"For field operations in {workspace_phrase}, I can turn the current context into a work queue, but the system still needs live source evidence before decisions should be treated as operational instructions.",
        "data_work": f"For scattered data in {workspace_phrase}, the right workflow is ingestion first, then normalization, evidence linking, gap detection, and finally report or decision generation.",
        "general": f"I can help operate {workspace_phrase} by turning the available evidence into priorities, reports, checklists, and decisions. Right now the safest answer is to separate what is already known from what still needs live evidence.",
    }
    plans = {
        "irrigation": ["Map field/block profile, crop, soil, acreage, and water budget.", "Attach recent controller events, flow, ET/weather, and soil/field observations.", "Flag stale or missing measurements before recommending runtime or volume.", "Generate an operator checklist and reviewer-safe irrigation decision."],
        "compliance": ["Collect water accounting, source provenance, field activity, and reporting period boundaries.", "Link every claim to an evidence record or mark it as missing.", "Draft the packet with reviewer-safe language and a missing-evidence appendix.", "Create follow-up tasks for unresolved gaps before customer or agency delivery."],
        "integration": ["Verify each connector or upload path separately.", "Normalize records into fields, telemetry, evidence, decisions, and reports.", "Run freshness and completeness checks after every ingest.", "Expose only customer-safe readiness status in the portal."],
        "field_ops": ["Convert the current context into field priorities and exceptions.", "Create tasks for missing evidence, source setup, and operator confirmation.", "Keep decisions in review until live evidence is attached.", "Generate an audit trail for every action taken in the workspace."],
        "data_work": ["Ingest files and machine data without losing source identity.", "Classify records by field, date, source, event type, and confidence.", "Detect duplicates, stale records, missing periods, and contradictions.", "Turn the clean evidence graph into decisions, reports, and next actions."],
        "general": ["Separate available evidence from missing evidence.", "Find the highest-risk blocker first.", "Create the next operating task instead of giving a vague answer.", "Escalate to report, assurance, or decision mode when enough evidence exists."],
    }
    next_actions = [
        "Connect WiseConn, Talgil, John Deere, ET/weather, or upload the latest exports.",
        "Confirm the field profile: crop, acreage, soil, water budget, and reporting period.",
        "Attach recent telemetry or operator notes before approving operational recommendations.",
    ]
    if missing:
        next_actions.insert(0, f"Resolve the first missing evidence item: {missing[0]}.")
    return {
        "summary": intent_summaries[intent],
        "answer": intent_summaries[intent],
        "available_data": available,
        "missing_data": missing,
        "integration_status": _integration_status(),
        "agent_plan": plans[intent],
        "work_completed": ["Read the tenant-scoped workspace context.", "Separated current evidence from missing operating evidence.", "Prepared a safe next-step plan without inventing live data."],
        "recommendations": plans[intent][:3],
        "next_actions": next_actions,
        "risk_flags": ["Do not treat sample or incomplete evidence as live operating truth.", "Do not issue irrigation, compliance, or customer-facing claims until source provenance is attached."],
        "confidence": "low" if missing else "medium",
        "customer_safe": True,
        "agent_mode": "deterministic_operating_plan",
    }


def _weak_or_empty(body: dict[str, Any]) -> bool:
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
    bad = ["reasoning-only", "no customer-safe answer", "ai provider returned no customer-safe final answer", "<think>", "okay, so i'm", "i'm trying to figure"]
    return any(marker in primary for marker in bad)


async def _run_ai(
    *,
    task: str,
    user_instruction: str,
    context: EvidenceContext,
    temperature: float = 0.2,
    history: list[dict[str, Any]] | None = None,
    audience: str | None = None,
    uploaded_evidence: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], Any]:
    router = ModelRouter()
    if is_local_ai():
        messages = compact_local_messages(
            question=user_instruction,
            context=context,
            history=history,
            audience=audience,
            uploaded_evidence=uploaded_evidence,
        )
        result, _selection = await router.run(
            task=TASK_PROFILE_MAP.get(task, "chat"),
            messages=messages,
            temperature=temperature,
            response_format=None,
        )
        answer = str(result.content or "").strip()
        if not answer or result.status != "ok":
            body = _deterministic_body(context)
            fallback_answer = str(body.get("summary") or "AGRO-AI could not produce a live local answer.")
            return local_plain_body(fallback_answer, context, question=user_instruction), result
        return local_plain_body(answer, context, question=user_instruction), result

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{PLANNER_PROMPT}\n\n"
                f"Task: {task}\n"
                f"Task instruction: {task_instruction}\n"
                f"User request: {user_instruction}\n"
                f"Tenant evidence context JSON: {context_json}"
            ),
        },
    ]
    plan_result, _selection = await router.run(task=model_task, messages=planner_messages, temperature=0.1, response_format={"type": "json_object"})
    plan_body = parse_model_json(plan_result.content)

    if plan_result.status != "ok" or plan_result.demo_fallback or plan_body.get("_safe_mode"):
        return _deterministic_body(context, user_instruction=user_instruction, task=task), plan_result

    final_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{FINAL_AGENT_PROMPT}\n\n"
                f"Task: {task}\n"
                f"Task instruction: {task_instruction}\n"
                f"User request: {user_instruction}\n"
                f"Execution plan JSON: {json.dumps(plan_body, default=str)}\n"
                f"Tenant evidence context JSON: {context_json}"
            ),
        },
    ]
    answer_result, _selection = await router.run(task=model_task, messages=final_messages, temperature=temperature, response_format={"type": "json_object"})
    body = parse_model_json(answer_result.content)

    if answer_result.status != "ok" or answer_result.demo_fallback or body.get("_safe_mode") or _weak_or_empty(body):
        fallback = _deterministic_body(context, user_instruction=user_instruction, task=task)
        fallback["work_completed"] = list(dict.fromkeys((fallback.get("work_completed") or []) + ["Attempted live model execution, but no customer-safe answer was returned."]))
        return fallback, answer_result

    return _normalize_agent_body(body, plan_body, context), answer_result


@router.get("/ai/status", response_model=AIStatusResponse)
async def ai_status() -> AIStatusResponse:
    model_router = ModelRouter()
    return AIStatusResponse(**model_router.status())


@router.get("/ai/context", response_model=EvidenceContext)
async def ai_context(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> EvidenceContext:
    return _get_evidence_context(db=db, tenant_id=tenant_id)


@router.post("/ai/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> ChatResponse:
    context = _get_evidence_context(db=db, tenant_id=tenant_id, block_id=payload.block_id, workspace_id=payload.workspace_id)
    body, result = await _run_ai(task="chat", user_instruction=payload.message, context=context, temperature=payload.temperature)
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


async def _structured_endpoint(*, task: str, instruction: str, block_id: str | None, workspace_id: str | None, tenant_id: str, db: Session) -> AgentRunResponse:
    context = _get_evidence_context(db=db, tenant_id=tenant_id, block_id=block_id, workspace_id=workspace_id)
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
async def irrigation_recommendation(payload: AgentRunRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> AgentRunResponse:
    return await _structured_endpoint(task="irrigation_recommendation", instruction=str(payload.inputs or {}), block_id=payload.block_id, workspace_id=payload.workspace_id, tenant_id=tenant_id, db=db)


@router.post("/ai/assurance-review", response_model=AgentRunResponse)
async def assurance_review(payload: AgentRunRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> AgentRunResponse:
    return await _structured_endpoint(task="assurance_review", instruction=str(payload.inputs or {}), block_id=payload.block_id, workspace_id=payload.workspace_id, tenant_id=tenant_id, db=db)


@router.post("/ai/report-draft", response_model=AgentRunResponse)
async def report_draft(payload: AgentRunRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> AgentRunResponse:
    return await _structured_endpoint(task="report_draft", instruction=str(payload.inputs or {}), block_id=payload.block_id, workspace_id=payload.workspace_id, tenant_id=tenant_id, db=db)


@router.post("/ai/integration-diagnosis", response_model=AgentRunResponse)
async def integration_diagnosis(payload: AgentRunRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> AgentRunResponse:
    return await _structured_endpoint(task="integration_diagnosis", instruction=str(payload.inputs or {}), block_id=payload.block_id, workspace_id=payload.workspace_id, tenant_id=tenant_id, db=db)


@router.post("/agents/run", response_model=AgentRunResponse)
async def run_agent(payload: AgentRunRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> AgentRunResponse:
    return await _structured_endpoint(task=payload.task, instruction=str(payload.inputs or {}), block_id=payload.block_id, workspace_id=payload.workspace_id, tenant_id=tenant_id, db=db)

"""Commercial AGRO-AI Intelligence Run API for developer integrations.

This is the narrow, billable front door for agricultural intelligence. It
reuses the hardened Platform API identity, scoping, idempotency, metering and
model-routing layers instead of creating a parallel auth or billing system.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.ai import _run_ai, _verification
from app.db.base import get_db
from app.models.operational_records import EvidenceRecord, IntelligenceRun
from app.models.platform_api import ApiProject
from app.models.saas import ManagedEntity
from app.platform_api.credits import commit_credits, release_credits, reserve_credits
from app.platform_api.deps import require_platform_api_principal
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.restrictions import enforce_resource_access
from app.platform_api.scopes import require_scopes
from app.schemas.ai import EvidenceContext, ToolCitation


router = APIRouter(prefix="/platform/intelligence", tags=["platform-intelligence-api"])

Task = Literal[
    "general",
    "field_diagnosis",
    "irrigation_plan",
    "crop_risk",
    "evidence_analysis",
    "report",
    "integration_diagnosis",
]

TASK_TO_ENGINE = {
    "general": "chat",
    "field_diagnosis": "irrigation_recommendation",
    "irrigation_plan": "irrigation_recommendation",
    "crop_risk": "gap_analysis",
    "evidence_analysis": "assurance_review",
    "report": "report_draft",
    "integration_diagnosis": "integration_diagnosis",
}

TASK_TO_COST = {
    "general": "recommendation_computation",
    "field_diagnosis": "recommendation_computation",
    "irrigation_plan": "recommendation_computation",
    "crop_risk": "recommendation_computation",
    "evidence_analysis": "recommendation_computation",
    "report": "report_generation",
    "integration_diagnosis": "recommendation_computation",
}

TASK_TO_SCOPE = {
    "report": "reports:read",
}


class IntelligenceRunCreate(BaseModel):
    """One-call agricultural intelligence request.

    `input` supports stateless use. `field_id` adds project-scoped AGRO-AI state
    and evidence when the customer wants a persistent integration.
    """

    model_config = ConfigDict(extra="forbid")

    task: Task = "general"
    question: str = Field(min_length=1, max_length=6000)
    field_id: str | None = Field(default=None, max_length=120)
    input: dict[str, Any] = Field(default_factory=dict)
    audience: str | None = Field(default=None, max_length=240)
    language: str | None = Field(default=None, max_length=40)

    @field_validator("input")
    @classmethod
    def bounded_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, default=str, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 128_000:
            raise ValueError("input must be 128 KB or smaller")
        lowered = {str(key).lower() for key in value}
        forbidden = {"api_key", "apikey", "password", "secret", "authorization", "credential"}
        if lowered & forbidden:
            raise ValueError("input must not contain credentials or secrets")
        return value


class IntelligenceRunPublic(BaseModel):
    id: str
    object: str = "agroai.intelligence_run"
    created_at: str
    status: Literal["completed", "needs_more_data", "unavailable"]
    task: str
    decision: dict[str, Any] = Field(default_factory=dict)
    summary: str
    findings: list[Any] = Field(default_factory=list)
    recommendations: list[Any] = Field(default_factory=list)
    next_actions: list[Any] = Field(default_factory=list)
    confidence: str
    risk_flags: list[Any] = Field(default_factory=list)
    missing_data: list[Any] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    provider: str | None = None


def _project(db: Session, principal: PlatformPrincipal) -> ApiProject:
    row = (
        db.query(ApiProject)
        .filter(
            ApiProject.id == principal.api_project_id,
            ApiProject.organization_id == principal.organization_id,
            ApiProject.status == "active",
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=401, detail={"code": "api_project_inactive"})
    return row


def _field_context(
    db: Session,
    principal: PlatformPrincipal,
    project: ApiProject,
    field_id: str | None,
) -> tuple[list[dict[str, Any]], list[ToolCitation], str | None, str | None, list[str]]:
    evidence: list[dict[str, Any]] = []
    citations: list[ToolCitation] = []
    crop: str | None = None
    workspace_id = principal.workspace_id
    missing: list[str] = []

    if not field_id:
        return evidence, citations, crop, workspace_id, missing

    enforce_resource_access(principal, resource_id=field_id, resource_type="field")
    field = (
        db.query(ManagedEntity)
        .filter(
            ManagedEntity.id == field_id,
            ManagedEntity.organization_id == principal.organization_id,
            ManagedEntity.entity_type == "platform_field",
            ManagedEntity.metadata_json["api_project_id"].as_string() == principal.api_project_id,
        )
        .first()
    )
    if field is None:
        if project.environment == "test":
            missing.append("persistent field record; this TEST project may be using synthetic fixtures")
            return evidence, citations, crop, workspace_id, missing
        raise HTTPException(status_code=404, detail={"code": "field_not_found"})

    metadata = dict(field.metadata_json or {})
    crop = metadata.get("crop")
    workspace_id = field.workspace_id or workspace_id
    evidence.append(
        {
            "type": "field",
            "id": field.id,
            "name": field.display_name,
            "crop": crop,
            "area_hectares": metadata.get("area_hectares"),
            "boundary": metadata.get("boundary"),
            "metadata": metadata.get("customer_metadata") or {},
            "source": "platform_field",
            "synthetic": bool(metadata.get("synthetic")),
        }
    )
    citations.append(
        ToolCitation(
            source_type="platform_field",
            source_id=field.id,
            title=f"Field {field.display_name}",
            tenant_id=principal.organization_id,
            workspace_id=workspace_id,
            fields=["name", "crop", "area_hectares", "boundary"],
        )
    )

    query = db.query(EvidenceRecord).filter(
        EvidenceRecord.tenant_id == principal.organization_id,
        EvidenceRecord.field_id == field.id,
        EvidenceRecord.quality_status == "usable",
    )
    if workspace_id:
        query = query.filter(EvidenceRecord.workspace_id == workspace_id)
    rows = query.order_by(EvidenceRecord.occurred_at.desc().nullslast(), EvidenceRecord.created_at.desc()).limit(30).all()
    if not rows:
        missing.append("recent project-scoped evidence for the selected field")
    for row in rows:
        evidence.append(
            {
                "type": row.evidence_type,
                "id": row.id,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "title": row.title,
                "summary": row.summary,
                "value": row.value_json,
                "units": row.units,
                "confidence": row.confidence,
                "quality_status": row.quality_status,
                "source_excerpt": row.source_excerpt,
                "source": "evidence_record",
            }
        )
        citations.append(
            ToolCitation(
                source_type="evidence_record",
                source_id=row.id,
                title=row.citation_label or row.title,
                tenant_id=principal.organization_id,
                workspace_id=workspace_id,
                fields=["title", "summary", "value", "units", "confidence", "occurred_at"],
            )
        )
    return evidence, citations, crop, workspace_id, missing


def _direct_context(payload: IntelligenceRunCreate, principal: PlatformPrincipal) -> tuple[list[dict[str, Any]], list[ToolCitation]]:
    if not payload.input:
        return [], []
    safe_input = json.loads(json.dumps(payload.input, default=str))
    evidence = [{"type": "request_context", "source": "api_request", "data": safe_input}]
    citation = ToolCitation(
        source_type="api_request",
        source_id=principal.request_id or "request",
        title="Customer-supplied request context",
        tenant_id=principal.organization_id,
        workspace_id=principal.workspace_id,
        fields=sorted(str(key)[:120] for key in safe_input.keys())[:50],
    )
    return evidence, [citation]


def _result_body(
    *,
    run_id: str,
    task: str,
    raw: dict[str, Any],
    result: Any,
    context: EvidenceContext,
    credits: int,
) -> dict[str, Any]:
    verification = _verification(result.status, context)
    summary = str(
        raw.get("summary")
        or raw.get("answer")
        or raw.get("recommendation")
        or raw.get("proof_summary")
        or "AGRO-AI completed the intelligence run."
    )
    decision_value = raw.get("decision")
    if not isinstance(decision_value, dict):
        decision_value = {}
        if raw.get("recommendation"):
            decision_value["recommendation"] = raw.get("recommendation")
    missing = list(raw.get("missing_data") or context.missing_data or [])
    risks = list(raw.get("risk_flags") or [])
    status_name = "completed" if result.status == "ok" else "unavailable"
    if status_name == "completed" and missing:
        status_name = "needs_more_data"
    return IntelligenceRunPublic(
        id=run_id,
        created_at=datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        status=status_name,
        task=task,
        decision=decision_value,
        summary=summary,
        findings=list(raw.get("findings") or raw.get("available_data") or raw.get("evidence_used") or []),
        recommendations=list(raw.get("recommendations") or []),
        next_actions=list(raw.get("next_actions") or []),
        confidence=str(raw.get("confidence") or ("low" if missing else "medium")),
        risk_flags=risks,
        missing_data=missing,
        citations=[item.model_dump(mode="json") for item in context.citations],
        verification=verification.model_dump(mode="json"),
        usage={
            "unit": "agroai_intelligence_credit",
            "credits": max(0, int(credits)),
            "billable": bool(result.status == "ok" and credits > 0),
        },
        model=result.model,
        provider=result.provider,
    ).model_dump(mode="json")


@router.post("", response_model=IntelligenceRunPublic)
async def create_intelligence_run(
    payload: IntelligenceRunCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    required_scope = TASK_TO_SCOPE.get(payload.task, "recommendations:read")
    require_scopes(principal.scopes, {required_scope})
    project = _project(db, principal)

    idem, replay = begin_idempotent_operation(
        db,
        principal=principal,
        operation="intelligence.run",
        idempotency_key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if replay and idem and idem.response_json:
        return dict(idem.response_json)

    operation_id = TASK_TO_COST[payload.task]
    reservation = reserve_credits(
        db,
        principal=principal,
        operation_id=operation_id,
        logical_operation_id=idempotency_key,
    )

    run_id = f"intel_{uuid.uuid4().hex}"
    try:
        field_evidence, field_citations, crop, workspace_id, missing = _field_context(
            db, principal, project, payload.field_id
        )
        direct_evidence, direct_citations = _direct_context(payload, principal)
        evidence = [*field_evidence, *direct_evidence]
        citations = [*field_citations, *direct_citations]
        if not evidence:
            missing.append("agricultural context: provide input or a project-scoped field_id")

        context = EvidenceContext(
            organization_id=principal.organization_id,
            workspace_id=workspace_id,
            block_id=payload.field_id,
            crop_type=crop or str(payload.input.get("crop") or "") or None,
            region=str(payload.input.get("region") or payload.input.get("location") or "") or None,
            evidence=evidence,
            missing_data=list(dict.fromkeys(missing)),
            citations=citations,
        )

        instruction = payload.question
        if payload.audience:
            instruction = f"Audience: {payload.audience}. {instruction}"
        if payload.language:
            instruction = f"Respond in language code {payload.language}. {instruction}"
        if payload.input:
            instruction += "\nCustomer input JSON: " + json.dumps(payload.input, default=str, separators=(",", ":"))

        raw, result = await _run_ai(
            task=TASK_TO_ENGINE[payload.task],
            user_instruction=instruction,
            context=context,
        )

        credits = int(reservation.reserved_credits) if reservation and result.status == "ok" else 0
        body = _result_body(
            run_id=run_id,
            task=payload.task,
            raw=raw,
            result=result,
            context=context,
            credits=credits,
        )

        record = IntelligenceRun(
            id=run_id,
            tenant_id=principal.organization_id,
            workspace_id=workspace_id,
            user_id=None,
            run_type=f"platform_api:{payload.task}",
            question=payload.question,
            input_context_json={
                "api_project_id": principal.api_project_id,
                "field_id": payload.field_id,
                "environment": project.environment,
                "customer_input": payload.input,
            },
            output_json=body,
            citations_json=body["citations"],
            provenance_json={
                "request_id": principal.request_id,
                "api_project_id": principal.api_project_id,
                "api_key_id": principal.api_key_id,
                "operation_id": operation_id,
                "billable_credits": credits,
            },
            freshness_json={"generated_at": body["created_at"]},
            model_provider=result.provider,
            model_name=result.model,
            status=body["status"],
            error=result.error if result.status != "ok" else None,
        )
        db.add(record)

        if result.status == "ok":
            commit_credits(db, reservation, principal=principal, status_code=200)
        else:
            release_credits(db, reservation, reason="intelligence_provider_unavailable")

        complete_idempotent_operation(idem, response_status=200, response_json=body)
        db.commit()
        return body
    except HTTPException:
        release_credits(db, reservation, reason="intelligence_http_error")
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        try:
            release_credits(db, reservation, reason="intelligence_runtime_error")
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "intelligence_run_unavailable", "reason": exc.__class__.__name__},
        ) from exc


@router.get("/{run_id}", response_model=IntelligenceRunPublic)
def get_intelligence_run(
    run_id: str,
    principal: PlatformPrincipal = Depends(require_platform_api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_scopes(principal.scopes, {"recommendations:read"})
    row = (
        db.query(IntelligenceRun)
        .filter(
            IntelligenceRun.id == run_id,
            IntelligenceRun.tenant_id == principal.organization_id,
            IntelligenceRun.run_type.like("platform_api:%"),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "intelligence_run_not_found"})
    provenance = dict(row.provenance_json or {})
    if provenance.get("api_project_id") != principal.api_project_id:
        raise HTTPException(status_code=404, detail={"code": "intelligence_run_not_found"})
    return dict(row.output_json or {})

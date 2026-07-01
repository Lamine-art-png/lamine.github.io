"""Schemas for provider-agnostic AGRO-AI intelligence workflows."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ToolCitation(BaseModel):
    source_type: str
    source_id: str
    title: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    fields: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class EvidenceContext(BaseModel):
    organization_id: str
    workspace_id: str | None = None
    block_id: str | None = None
    crop_type: str | None = None
    region: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    citations: list[ToolCitation] = Field(default_factory=list)


class VerificationResult(BaseModel):
    status: Literal["verified", "partial", "unavailable"]
    missing_data: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    citations: list[ToolCitation] = Field(default_factory=list)


class AIStatusResponse(BaseModel):
    configured: bool
    provider: str
    base_url_present: bool
    model: str | None = None
    mode: Literal["openai_compatible", "ollama", "offline"]
    missing_env: list[str] = Field(default_factory=list)
    fallback_active: bool = False


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    workspace_id: str | None = None
    block_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0, le=1)


class ChatResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    output: str
    provider: str
    model: str | None = None
    demo_fallback: bool = False
    evidence_context: EvidenceContext
    citations: list[ToolCitation] = Field(default_factory=list)
    verification: VerificationResult
    raw: dict[str, Any] | None = None


class AgentRunRequest(BaseModel):
    task: Literal[
        "gap_analysis",
        "proof_draft",
        "readiness_refresh",
        "irrigation_recommendation",
        "integration_diagnosis",
    ] = "gap_analysis"
    workspace_id: str | None = None
    block_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    status: Literal["completed", "unavailable"]
    task: str
    output: dict[str, Any]
    provider: str
    model: str | None = None
    evidence_context: EvidenceContext
    citations: list[ToolCitation] = Field(default_factory=list)
    verification: VerificationResult
    demo_fallback: bool = False


class IntelligenceRunRequest(BaseModel):
    task: Literal[
        "chat",
        "field_diagnosis",
        "exception_triage",
        "decision_workbench",
        "report_factory",
        "connector_diagnosis",
        "readiness_analysis",
    ] = "chat"
    question: str = Field(..., min_length=1)
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)


class IntelligenceRunResponse(BaseModel):
    status: Literal["completed", "unavailable"]
    task: str
    model: str | None = None
    model_status: Literal["live", "fallback", "unavailable"]
    provider: str
    customer_status: Literal["ready", "needs_more_data", "using_safe_mode", "action_required"]
    customer_status_label: str
    internal_status: str | None = None
    internal_debug: dict[str, Any] = Field(default_factory=dict)
    sample_mode: bool = False
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any]
    citations: list[ToolCitation] = Field(default_factory=list)
    verification: VerificationResult
    missing_data: list[str] = Field(default_factory=list)
    confidence: str = "low"

    # Backward-compatible top-level fields for older deployed portal bundles.
    # This prevents the UI from showing only "Risk and confidence: low" while
    # Cloudflare is still serving a cached frontend build.
    summary: str | None = None
    answer: str | None = None
    evidence_used: list[Any] = Field(default_factory=list)
    missing_evidence: list[Any] = Field(default_factory=list)
    risk: list[Any] | str | None = None
    recommendation: Any = None
    next_action: Any = None

    @model_validator(mode="after")
    def fill_legacy_portal_fields(self) -> "IntelligenceRunResponse":
        result = self.result or {}
        summary = (
            self.summary
            or result.get("summary")
            or result.get("executive_summary")
            or result.get("recommendation")
            or result.get("why")
            or "AGRO-AI reviewed the workspace context and produced an operating response."
        )
        self.summary = str(summary)
        self.answer = self.answer or result.get("answer") or self.summary
        self.evidence_used = self.evidence_used or list(result.get("evidence_used") or result.get("available_data") or result.get("key_findings") or [])
        self.missing_evidence = self.missing_evidence or list(result.get("missing_evidence") or result.get("missing_data") or self.missing_data or [])
        self.risk = self.risk or result.get("risk_flags") or result.get("risks") or []
        self.recommendation = self.recommendation or result.get("recommendation") or result.get("recommendations") or []
        self.next_action = self.next_action or result.get("next_actions") or result.get("operator_instructions") or []
        return self

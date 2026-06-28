"""Schemas for provider-agnostic AGRO-AI intelligence workflows."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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

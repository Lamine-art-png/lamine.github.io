from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

TruthLabel = Literal["measured", "reported", "calculated", "estimated", "ai_inferred", "unknown"]


class FieldFact(BaseModel):
    name: str
    value: Any = None
    unit: str | None = None
    truth_label: TruthLabel = "unknown"
    source: str | None = None
    observed_at: str | None = None


class AgricultureRequest(BaseModel):
    tenant_id: str
    operation: Literal["reason", "recommend", "explain", "verify"]
    question: str
    field_id: str | None = None
    crop_cycle_id: str | None = None
    language: str = "en"
    facts: list[FieldFact] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = Field(default=900, ge=1, le=4096)


class AgricultureResponse(BaseModel):
    operation: str
    model: str
    answer: str
    field_id: str | None = None
    requested_tools: list[str] = Field(default_factory=list)
    truth_policy_applied: bool = True

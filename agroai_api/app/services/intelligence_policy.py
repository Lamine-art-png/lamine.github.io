"""Commercial and deterministic safety policy resolution for AGRO-AI intelligence."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.saas import Organization
from app.services.commercial_control import resolve_effective_entitlements


@dataclass(frozen=True)
class IntelligencePolicy:
    commercial_profile: str
    task_profile: str
    max_context_chars: int
    max_sources: int
    max_agent_steps: int
    max_tool_calls: int
    max_output_tokens: int
    max_model_attempts: int
    timeout_seconds: int
    reasoning_budget: str
    memory_scope: str
    cross_workspace_scope: bool
    portfolio_scope: bool
    deep_analysis_enabled: bool
    priority_class: str
    model_pool_class: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILE_BASE = {
    "essential": {
        "max_context_chars": 12000,
        "max_sources": 4,
        "max_agent_steps": 1,
        "max_tool_calls": 1,
        "max_output_tokens": 1200,
        "max_model_attempts": 2,
        "timeout_seconds": 24,
        "reasoning_budget": "bounded",
        "memory_scope": "workspace_limited",
        "cross_workspace_scope": False,
        "portfolio_scope": False,
        "deep_analysis_enabled": False,
        "priority_class": "standard",
        "model_pool_class": "efficient",
    },
    "operational": {
        "max_context_chars": 24000,
        "max_sources": 10,
        "max_agent_steps": 3,
        "max_tool_calls": 4,
        "max_output_tokens": 2400,
        "max_model_attempts": 4,
        "timeout_seconds": 42,
        "reasoning_budget": "operational",
        "memory_scope": "workspace",
        "cross_workspace_scope": False,
        "portfolio_scope": False,
        "deep_analysis_enabled": True,
        "priority_class": "normal",
        "model_pool_class": "reasoning",
    },
    "collaborative": {
        "max_context_chars": 42000,
        "max_sources": 25,
        "max_agent_steps": 8,
        "max_tool_calls": 10,
        "max_output_tokens": 3600,
        "max_model_attempts": 5,
        "timeout_seconds": 58,
        "reasoning_budget": "advanced",
        "memory_scope": "organization",
        "cross_workspace_scope": False,
        "portfolio_scope": False,
        "deep_analysis_enabled": True,
        "priority_class": "elevated",
        "model_pool_class": "advanced_reasoning",
    },
    "network": {
        "max_context_chars": 72000,
        "max_sources": 75,
        "max_agent_steps": 15,
        "max_tool_calls": 20,
        "max_output_tokens": 5200,
        "max_model_attempts": 6,
        "timeout_seconds": 75,
        "reasoning_budget": "network",
        "memory_scope": "cross_workspace",
        "cross_workspace_scope": True,
        "portfolio_scope": True,
        "deep_analysis_enabled": True,
        "priority_class": "high",
        "model_pool_class": "frontier_reasoning",
    },
    "institutional": {
        "max_context_chars": 100000,
        "max_sources": 120,
        "max_agent_steps": 24,
        "max_tool_calls": 32,
        "max_output_tokens": 6800,
        "max_model_attempts": 7,
        "timeout_seconds": 90,
        "reasoning_budget": "institutional",
        "memory_scope": "organization_governed",
        "cross_workspace_scope": True,
        "portfolio_scope": True,
        "deep_analysis_enabled": True,
        "priority_class": "contract",
        "model_pool_class": "frontier_failover",
    },
}


TASK_ADJUSTMENTS = {
    "fast": {"output_multiplier": 0.45, "context_multiplier": 0.6, "timeout_multiplier": 0.55, "attempt_delta": -1},
    "reasoning": {"output_multiplier": 1.0, "context_multiplier": 1.0, "timeout_multiplier": 1.0, "attempt_delta": 0},
    "report": {"output_multiplier": 1.35, "context_multiplier": 1.2, "timeout_multiplier": 1.15, "attempt_delta": 0},
}


def resolve_intelligence_policy(
    db: Session,
    org: Organization,
    *,
    task_profile: str,
    request_risk: str = "normal",
    evidence_available: bool = True,
    system_degraded: bool = False,
) -> IntelligencePolicy:
    effective = resolve_effective_entitlements(db, org)
    commercial_profile = str(effective.value("intelligence.profile", "essential"))
    base = dict(PROFILE_BASE.get(commercial_profile, PROFILE_BASE["essential"]))
    adjustment = TASK_ADJUSTMENTS.get(task_profile, TASK_ADJUSTMENTS["reasoning"])

    base["max_output_tokens"] = max(500, int(base["max_output_tokens"] * adjustment["output_multiplier"]))
    base["max_context_chars"] = max(6000, int(base["max_context_chars"] * adjustment["context_multiplier"]))
    base["timeout_seconds"] = max(12, min(90, int(base["timeout_seconds"] * adjustment["timeout_multiplier"])))
    base["max_model_attempts"] = max(1, base["max_model_attempts"] + int(adjustment["attempt_delta"]))

    if not effective.enabled("intelligence.deep_analysis"):
        base["deep_analysis_enabled"] = False
        base["max_agent_steps"] = min(base["max_agent_steps"], 2)
        base["max_tool_calls"] = min(base["max_tool_calls"], 2)
    if request_risk in {"high", "critical"}:
        base["max_agent_steps"] = min(base["max_agent_steps"], 3)
        base["max_tool_calls"] = min(base["max_tool_calls"], 4)
        base["reasoning_budget"] = "safety_bounded"
    if not evidence_available:
        base["max_sources"] = min(base["max_sources"], 8)
        base["reasoning_budget"] = "evidence_constrained"
    if system_degraded:
        base["max_model_attempts"] = min(base["max_model_attempts"], 2)
        base["timeout_seconds"] = min(base["timeout_seconds"], 30)
        base["priority_class"] = "degraded"

    return IntelligencePolicy(commercial_profile=commercial_profile, task_profile=task_profile, **base)


# ---------------------------------------------------------------------------
# Deterministic action safety policy
# ---------------------------------------------------------------------------

ActionKind = Literal[
    "informational",
    "inspection",
    "data_collection",
    "operational_recommendation",
    "physical_execution",
    "chemical_application",
    "external_submission",
]

_CHEMICAL_TERMS = (
    "pesticide", "herbicide", "fungicide", "insecticide", "chemical",
    "spray", "fertilizer", "fertiliser", "nutrient application", "dose", "dosage",
)
_EXTERNAL_TERMS = ("submit", "file with", "send externally", "publish", "transmit to", "report to regulator")
_PHYSICAL_PATTERNS = (
    r"\birrigate\b",
    r"\bwater\s+(?:the\s+)?(?:field|block|zone|crop|row|orchard|vineyard)\b",
    r"\b(?:start|stop|run|activate|deactivate|open|close)\b.{0,40}\b(?:zone|valve|pump|controller|irrigation|motor|equipment)\b",
    r"\b(?:zone|valve|pump|controller|irrigation|motor|equipment)\b.{0,40}\b(?:start|stop|run|activate|deactivate|open|close)\b",
)
_EXECUTABLE_INSTRUCTION_PATTERNS = (
    r"\b(?:irrigate|spray|fertilize|fertilise|apply|dose|submit|publish|transmit)\b",
    r"\b(?:start|stop|run|activate|deactivate|open|close)\b.{0,50}\b(?:zone|valve|pump|controller|irrigation|motor|equipment)\b",
    r"\b(?:zone|valve|pump|controller|irrigation|motor|equipment)\b.{0,50}\b(?:start|stop|run|activate|deactivate|open|close)\b",
)
_INFORMATIONAL_PREFIXES = (
    "summarize ", "summarise ", "explain ", "describe ", "compare ", "document ",
    "list ", "show ", "review the report", "review the evidence", "review the data",
)
_INSPECTION_PREFIXES = ("inspect ", "check ", "visually inspect ", "review the field", "review the equipment")
_DATA_COLLECTION_PREFIXES = (
    "measure ", "collect ", "capture ", "sample ", "record ", "verify ", "confirm ",
    "re-read ", "reread ", "obtain ", "request a reading", "monitor ",
)


def _normalize_action_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def classify_action_kind(action: str) -> ActionKind:
    """Conservatively classify actions without trusting model-supplied labels."""
    text = _normalize_action_text(action)
    if not text:
        return "operational_recommendation"
    if any(term in text for term in _CHEMICAL_TERMS):
        return "chemical_application"
    if any(term in text for term in _EXTERNAL_TERMS):
        return "external_submission"
    if any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in _PHYSICAL_PATTERNS):
        return "physical_execution"
    if text.startswith(_DATA_COLLECTION_PREFIXES):
        return "data_collection"
    if text.startswith(_INSPECTION_PREFIXES):
        return "inspection"
    if text.startswith(_INFORMATIONAL_PREFIXES):
        return "informational"
    return "operational_recommendation"


def action_requires_human_approval(kind: ActionKind) -> bool:
    return kind in {"operational_recommendation", "physical_execution", "chemical_application", "external_submission"}


def contains_consequential_action(text: str) -> bool:
    normalized = _normalize_action_text(text)
    if not normalized:
        return False
    if any(term in normalized for term in _CHEMICAL_TERMS + _EXTERNAL_TERMS):
        return True
    return any(re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL) for pattern in _PHYSICAL_PATTERNS)


def contains_executable_instruction(text: str) -> bool:
    """Detect free-form instructions that a recovery model must never issue."""
    normalized = _normalize_action_text(text)
    if not normalized:
        return False
    if any(re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL) for pattern in _EXECUTABLE_INSTRUCTION_PATTERNS):
        # Avoid treating explicit inability/withholding statements as instructions.
        if re.search(r"\b(?:cannot|can't|unable to|withheld|do not have enough evidence to|not enough evidence to)\b.{0,35}\b(?:recommend|determine|authorize)\b", normalized):
            return False
        return True
    return False

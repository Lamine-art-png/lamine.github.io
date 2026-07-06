"""Commercial intelligence policy resolution.

Task profiles describe what the user is doing. Commercial profiles describe the
allowed depth, scope, and cost envelope for the organization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models.saas import Organization
from app.services.entitlements import resolve_effective_entitlements


TaskProfile = Literal["fast", "reasoning", "report"]


@dataclass(frozen=True)
class IntelligencePolicy:
    commercial_profile: str
    task_profile: TaskProfile
    max_context_class: str
    retrieval_depth: int
    max_sources: int
    max_agent_steps: int
    max_tool_calls: int
    memory_scope: str
    cross_workspace_scope: bool
    reasoning_budget: str
    output_budget: str
    timeout_class: str
    priority_class: str
    model_pool_class: str
    fallback_budget: int
    deep_analysis_enabled: bool


PROFILE_BASE = {
    "essential": {
        "max_context_class": "workspace_summary",
        "retrieval_depth": 1,
        "max_sources": 3,
        "max_agent_steps": 0,
        "max_tool_calls": 1,
        "memory_scope": "none",
        "cross_workspace_scope": False,
        "reasoning_budget": "bounded",
        "output_budget": "compact",
        "timeout_class": "standard",
        "priority_class": "standard",
        "model_pool_class": "standard",
        "fallback_budget": 0,
        "deep_analysis_enabled": False,
    },
    "operational": {
        "max_context_class": "workspace_evidence",
        "retrieval_depth": 2,
        "max_sources": 8,
        "max_agent_steps": 2,
        "max_tool_calls": 4,
        "memory_scope": "workspace",
        "cross_workspace_scope": False,
        "reasoning_budget": "medium",
        "output_budget": "standard",
        "timeout_class": "standard",
        "priority_class": "standard",
        "model_pool_class": "operational",
        "fallback_budget": 1,
        "deep_analysis_enabled": True,
    },
    "collaborative": {
        "max_context_class": "organization_workspace",
        "retrieval_depth": 3,
        "max_sources": 16,
        "max_agent_steps": 4,
        "max_tool_calls": 8,
        "memory_scope": "team",
        "cross_workspace_scope": False,
        "reasoning_budget": "elevated",
        "output_budget": "standard",
        "timeout_class": "standard",
        "priority_class": "standard",
        "model_pool_class": "collaborative",
        "fallback_budget": 1,
        "deep_analysis_enabled": True,
    },
    "network": {
        "max_context_class": "portfolio",
        "retrieval_depth": 4,
        "max_sources": 32,
        "max_agent_steps": 6,
        "max_tool_calls": 12,
        "memory_scope": "organization",
        "cross_workspace_scope": True,
        "reasoning_budget": "high",
        "output_budget": "expanded",
        "timeout_class": "extended",
        "priority_class": "elevated",
        "model_pool_class": "network",
        "fallback_budget": 2,
        "deep_analysis_enabled": True,
    },
    "institutional": {
        "max_context_class": "contract_scope",
        "retrieval_depth": 5,
        "max_sources": 48,
        "max_agent_steps": 8,
        "max_tool_calls": 16,
        "memory_scope": "contract",
        "cross_workspace_scope": True,
        "reasoning_budget": "contract",
        "output_budget": "expanded",
        "timeout_class": "contract",
        "priority_class": "contract",
        "model_pool_class": "institutional",
        "fallback_budget": 2,
        "deep_analysis_enabled": True,
    },
}


TASK_MULTIPLIERS = {
    "fast": {"retrieval_depth": -1, "max_sources": -2, "max_tool_calls": -1, "output_budget": "compact"},
    "reasoning": {},
    "report": {"retrieval_depth": 1, "max_sources": 4, "max_tool_calls": 2, "output_budget": "expanded"},
}


def resolve_intelligence_policy(org: Organization, task_profile: TaskProfile = "reasoning") -> IntelligencePolicy:
    effective = resolve_effective_entitlements(org)
    profile = str(effective.values.get("intelligence.profile") or "essential")
    base = dict(PROFILE_BASE.get(profile, PROFILE_BASE["essential"]))
    for key, delta in TASK_MULTIPLIERS.get(task_profile, {}).items():
        if isinstance(delta, int):
            base[key] = max(0, int(base[key]) + delta)
        else:
            base[key] = delta
    return IntelligencePolicy(commercial_profile=profile, task_profile=task_profile, **base)

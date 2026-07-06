"""Bind the live Brain route to commercial intelligence policy at runtime."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from app.models.saas import Organization
from app.services.commercial_live_intelligence import CommercialLiveIntelligence
from app.services.intelligence_context import build_intelligence_context as _base_build_intelligence_context
from app.services.intelligence_policy import resolve_intelligence_policy
from app.services.live_intelligence import LiveIntelligence


_RUNTIME_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("agroai_brain_commercial_runtime", default=None)


def build_commercial_intelligence_context(**kwargs) -> dict[str, Any]:
    """Build normal tenant-safe context and retain request-local policy inputs."""
    bundle = _base_build_intelligence_context(**kwargs)
    db = kwargs["db"]
    tenant_id = kwargs["tenant_id"]
    org = db.query(Organization).filter(Organization.id == tenant_id).first()
    if org is None:
        raise ValueError("Organization not found")
    evidence_context = bundle.get("evidence_context")
    evidence_available = bool(getattr(evidence_context, "evidence", None))
    _RUNTIME_CONTEXT.set({"db": db, "org": org, "evidence_available": evidence_available})
    return bundle


class ContextualCommercialLiveIntelligence:
    """No-argument Brain-compatible facade over CommercialLiveIntelligence."""

    async def run(
        self,
        task: str,
        question: str,
        messages: list[dict[str, str]],
        preferred_language: str | None,
    ):
        context = _RUNTIME_CONTEXT.get()
        if not context:
            # Health/smoke callers that do not build Brain context retain the hardened
            # base runtime instead of receiving a fake policy or fabricated tenant.
            return await LiveIntelligence().run(task, question, messages, preferred_language)

        try:
            task_profile = LiveIntelligence().profile(task, question)
            policy = resolve_intelligence_policy(
                context["db"],
                context["org"],
                task_profile=task_profile,
                evidence_available=bool(context["evidence_available"]),
            )
            runtime = CommercialLiveIntelligence(policy)
            return await runtime.run(task, question, messages, preferred_language)
        finally:
            _RUNTIME_CONTEXT.set(None)


def install_brain_commercial_runtime() -> None:
    """Install after the Brain module is fully loaded and before requests are served."""
    from app.api.v1 import brain as brain_api

    brain_api.build_intelligence_context = build_commercial_intelligence_context
    brain_api.LiveIntelligence = ContextualCommercialLiveIntelligence

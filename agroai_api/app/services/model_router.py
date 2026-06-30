"""Task-aware model selection for AGRO-AI intelligence routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.ai_gateway import AIGateway, AIGatewayResult


# Chinese-first frontier routing for the AGRO-AI operating brain.
# Operators can still override these with env vars, but the production default
# should favor models currently positioned for agentic work, long-context RAG,
# tool use, and natural enterprise dialogue instead of a brittle single model id.
DEFAULT_FRONTIER_MODEL = "z-ai/glm-5-turbo"
DEFAULT_FAST_MODEL = "qwen/qwen3-next-80b-a3b-instruct"
DEFAULT_REPORT_MODEL = "qwen/qwen3-max"
DEFAULT_MODEL_FALLBACKS = [
    "z-ai/glm-5-turbo",
    "qwen/qwen3-max",
    "qwen/qwen3-coder",
    "qwen/qwen3-235b-a22b-instruct-2507",
    "z-ai/glm-4.5-air",
]

TASK_PROFILES = {
    "chat": "reasoning",
    "readiness_analysis": "reasoning",
    "field_diagnosis": "reasoning",
    "exception_triage": "reasoning",
    "decision_workbench": "reasoning",
    "report_factory": "report",
    "connector_diagnosis": "reasoning",
}


@dataclass
class ModelSelection:
    task: str
    profile: str
    model: str | None


class ModelRouter:
    def __init__(self) -> None:
        self.gateway = AIGateway()
        configured_default = (settings.AI_MODEL or "").strip()
        self.default_model = configured_default or DEFAULT_FRONTIER_MODEL
        self.fast_model = (settings.AI_FAST_MODEL or "").strip() or DEFAULT_FAST_MODEL
        self.reasoning_model = (settings.AI_REASONING_MODEL or "").strip() or DEFAULT_FRONTIER_MODEL
        self.report_model = (settings.AI_REPORT_MODEL or "").strip() or DEFAULT_REPORT_MODEL
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip() or self.default_model
        configured_fallbacks = [
            model.strip()
            for model in (settings.AI_MODEL_FALLBACKS or "").split(",")
            if model.strip()
        ]
        self.fallback_models = []
        for model in [*configured_fallbacks, *DEFAULT_MODEL_FALLBACKS]:
            if model and model not in self.fallback_models:
                self.fallback_models.append(model)

    def mode(self) -> str:
        provider = (settings.AI_PROVIDER or "").strip().lower()
        if provider == "ollama":
            return "ollama"
        if provider:
            return "openai_compatible"
        return "offline"

    def missing_env(self) -> list[str]:
        provider = (settings.AI_PROVIDER or "").strip().lower()
        missing: list[str] = []
        if not settings.AI_PROVIDER:
            missing.append("AI_PROVIDER")
        if not settings.AI_BASE_URL:
            missing.append("AI_BASE_URL")
        if provider not in {"", "ollama"} and not settings.AI_API_KEY:
            missing.append("AI_API_KEY")
        return missing

    def status(self) -> dict[str, Any]:
        selected = self.select("chat")
        return {
            "configured": self.gateway.is_configured,
            "provider": self.gateway.provider or "offline",
            "base_url_present": bool(self.gateway.base_url),
            "model": selected.model,
            "mode": self.mode(),
            "missing_env": self.missing_env(),
            "fallback_active": not self.gateway.is_configured,
            "profiles": {
                "fast": self.fast_model,
                "reasoning": self.reasoning_model,
                "report": self.report_model,
                "fallbacks": self.fallback_models,
            },
        }

    def select(self, task: str) -> ModelSelection:
        profile = TASK_PROFILES.get(task, "reasoning")
        model = self.fast_model
        if profile == "reasoning":
            model = self.reasoning_model
        elif profile == "report":
            model = self.report_model
        if self.mode() == "ollama" and self.local_model:
            model = self.local_model
        return ModelSelection(task=task, profile=profile, model=model or None)

    async def run(
        self,
        *,
        task: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[AIGatewayResult, ModelSelection]:
        selection = self.select(task)
        chat_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "response_format": response_format,
        }
        if selection.model and selection.model != self.gateway.model:
            chat_kwargs["model_override"] = selection.model
        result = await self.gateway.chat(messages, **chat_kwargs)
        return result, selection

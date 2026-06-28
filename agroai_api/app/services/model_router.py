"""Task-aware model selection for AGRO-AI intelligence routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.ai_gateway import AIGateway, AIGatewayResult


TASK_PROFILES = {
    "chat": "fast",
    "readiness_analysis": "fast",
    "field_diagnosis": "reasoning",
    "exception_triage": "reasoning",
    "decision_workbench": "reasoning",
    "report_factory": "report",
    "connector_diagnosis": "fast",
}


@dataclass
class ModelSelection:
    task: str
    profile: str
    model: str | None


class ModelRouter:
    def __init__(self) -> None:
        self.gateway = AIGateway()
        self.default_model = (settings.AI_MODEL or "").strip()
        self.fast_model = (settings.AI_FAST_MODEL or "").strip() or self.default_model
        self.reasoning_model = (settings.AI_REASONING_MODEL or "").strip() or self.default_model
        self.report_model = (settings.AI_REPORT_MODEL or "").strip() or self.default_model
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip() or self.default_model

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
        if not settings.AI_MODEL and not settings.AI_LOCAL_MODEL:
            missing.append("AI_MODEL")
        if provider not in {"", "ollama"} and not settings.AI_API_KEY:
            missing.append("AI_API_KEY")
        return missing

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.gateway.is_configured,
            "provider": self.gateway.provider or "offline",
            "base_url_present": bool(self.gateway.base_url),
            "model": self.default_model or self.local_model or None,
            "mode": self.mode(),
            "missing_env": self.missing_env(),
            "fallback_active": not self.gateway.is_configured,
        }

    def select(self, task: str) -> ModelSelection:
        profile = TASK_PROFILES.get(task, "fast")
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

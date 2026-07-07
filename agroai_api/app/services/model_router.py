"""Task-aware model selection for AGRO-AI intelligence routes."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.ai_gateway import AIGateway, AIGatewayResult
from app.services.hosted_ui_translation import run_hosted_ui_translation
from app.services.live_intelligence import LiveIntelligence
from app.services.local_ui_translation import run_local_ui_translation

DEFAULT_FRONTIER_MODEL = "z-ai/glm-5.2"
DEFAULT_FAST_MODEL = "qwen/qwen3-next-80b-a3b-instruct"
DEFAULT_REPORT_MODEL = "qwen/qwen3-max"
DEFAULT_MODEL_FALLBACKS = ["qwen/qwen3-next-80b-a3b-instruct","z-ai/glm-5-turbo","z-ai/glm-4.5-air","qwen/qwen3-max","z-ai/glm-5.2","z-ai/glm-4.5","deepseek/deepseek-v3.1-terminus"]

TASK_PROFILES = {"chat":"reasoning","ui_translation":"fast","readiness_analysis":"reasoning","field_diagnosis":"reasoning","exception_triage":"reasoning","decision_workbench":"reasoning","report_factory":"report","connector_diagnosis":"reasoning"}


@dataclass
class ModelSelection:
    task: str
    profile: str
    model: str | None


def _extract_question(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        for pattern in (r"Exact current question:\s*(.+?)(?:\n|$)",r"Exact user question:\s*(.+?)(?:\n|$)",r"Question:\s*(.+?)(?:\n|$)",r"QUESTION:\s*(.+?)(?:\n|$)"):
            match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()[:1600]
        if content.strip():
            return content.strip()[:1600]
    return ""


def _extract_preferred_language(messages: list[dict[str, str]]) -> str | None:
    for message in reversed(messages):
        content = str(message.get("content") or "")
        for pattern in (r"Preferred portal language code:\s*([A-Za-z0-9_-]+)",r"Preferred portal language:\s*[^\n(]*\(([A-Za-z0-9_-]+)\)",r"Preferred portal language:\s*([A-Za-z0-9_-]+)"):
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return None


class ModelRouter:
    def __init__(self) -> None:
        self.gateway = AIGateway()
        configured_default = (settings.AI_MODEL or "").strip()
        self.default_model = configured_default or DEFAULT_FRONTIER_MODEL
        self.fast_model = (settings.AI_FAST_MODEL or "").strip() or DEFAULT_FAST_MODEL
        self.reasoning_model = (settings.AI_REASONING_MODEL or "").strip() or self.default_model
        self.report_model = (settings.AI_REPORT_MODEL or "").strip() or DEFAULT_REPORT_MODEL
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip()
        configured = [x.strip() for x in (settings.AI_MODEL_FALLBACKS or "").split(",") if x.strip()]
        self.fallback_models: list[str] = []
        for model in [*configured,*DEFAULT_MODEL_FALLBACKS]:
            if model and model not in self.fallback_models:
                self.fallback_models.append(model)
        # AIGateway owns the actual retry loop. Keep its candidate set aligned
        # with the task router's configured + safe default fallbacks.
        self.gateway.fallback_models = list(self.fallback_models)

    def mode(self) -> str:
        provider = (settings.AI_PROVIDER or "").strip().lower()
        if provider == "ollama": return "ollama"
        if provider: return "openai_compatible"
        return "offline"

    def missing_env(self) -> list[str]:
        provider = (settings.AI_PROVIDER or "").strip().lower()
        if not provider:
            return ["AI_PROVIDER"]
        if provider == "ollama":
            missing = []
            if not settings.AI_BASE_URL: missing.append("AI_BASE_URL")
            if not settings.AI_LOCAL_MODEL and (not settings.AI_MODEL or "/" in settings.AI_MODEL): missing.append("AI_LOCAL_MODEL")
            return missing
        if provider in {"openrouter","openrouter.ai"}:
            return [] if (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY")) else ["AI_API_KEY_OR_OPENROUTER_API_KEY"]
        missing = []
        if not settings.AI_BASE_URL: missing.append("AI_BASE_URL")
        if not settings.AI_API_KEY: missing.append("AI_API_KEY")
        return missing

    def status(self) -> dict[str, Any]:
        selected = self.select("chat")
        return {"configured":not bool(self.missing_env()),"provider":self.gateway.raw_provider or self.gateway.provider or "offline","base_url_present":bool(self.gateway.base_url),"model":selected.model,"mode":self.mode(),"missing_env":self.missing_env(),"fallback_active":bool(self.missing_env()),"profiles":{"fast":self.fast_model,"reasoning":self.reasoning_model,"report":self.report_model,"fallbacks":self.fallback_models}}

    def select(self, task: str) -> ModelSelection:
        profile = TASK_PROFILES.get(task, "reasoning")
        model = self.reasoning_model
        if profile == "fast": model = self.fast_model
        elif profile == "report": model = self.report_model
        if self.mode() == "ollama":
            local = self.local_model or ((settings.AI_MODEL or "").strip() if "/" not in (settings.AI_MODEL or "") else "")
            model = local or None
        return ModelSelection(task=task, profile=profile, model=model or None)

    async def run(self, *, task: str, messages: list[dict[str, str]], temperature: float = 0.2, response_format: dict[str, Any] | None = None, max_tokens: int | None = None, timeout_seconds: int | None = None, max_model_attempts: int | None = None) -> tuple[AIGatewayResult, ModelSelection]:
        selection = self.select(task)
        if task == "ui_translation" and response_format is not None and self.mode() == "ollama":
            local_result = await run_local_ui_translation(
                base_url=self.gateway.base_url,
                model=selection.model or "",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
            if local_result.status == "ok":
                return local_result, selection

            hosted_result = await run_hosted_ui_translation(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
            if hosted_result.status == "ok":
                hosted_selection = ModelSelection(task=task, profile="fast", model=hosted_result.model)
                return hosted_result, hosted_selection

            local_error = local_result.error or "local UI translation unavailable"
            hosted_error = hosted_result.error or "hosted UI translation unavailable"
            return AIGatewayResult(
                status="unavailable",
                content="",
                provider="ollama+openrouter",
                model=selection.model,
                error=f"Local translation failed: {local_error} | Hosted fallback failed: {hosted_error}",
            ), selection
        if response_format is None:
            question = _extract_question(messages)
            preferred_language = _extract_preferred_language(messages)
            live = await LiveIntelligence().run(task, question, messages, preferred_language)
            selected = ModelSelection(task=task, profile=live.profile, model=live.model)
            raw = {"response_language": live.response_language, "profile": live.profile}
            if live.status == "ok" and live.content.strip():
                return AIGatewayResult(status="ok",content=live.content.strip(),provider=live.provider,model=live.model,demo_fallback=False,raw=raw), selected
            if live.status == "language_generation_failed":
                return AIGatewayResult(status="language_generation_failed",content="",provider=live.provider,model=live.model,demo_fallback=False,raw=raw,error=live.error or "Language generation failed."), selected
            return AIGatewayResult(status="unavailable",content="",provider=live.provider,model=live.model,demo_fallback=False,raw=raw,error=live.error or "Live model unavailable."), selected

        kwargs: dict[str, Any] = {"temperature": temperature, "response_format": response_format}
        if selection.model and self.mode() != "offline": kwargs["model_override"] = selection.model
        if max_tokens is not None: kwargs["max_tokens"] = max_tokens
        if timeout_seconds is not None: kwargs["timeout_seconds"] = timeout_seconds
        if max_model_attempts is not None: kwargs["max_model_attempts"] = max_model_attempts
        return await self.gateway.chat(messages, **kwargs), selection

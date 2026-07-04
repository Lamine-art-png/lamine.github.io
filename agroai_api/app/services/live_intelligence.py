from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.services.language import language_matches_target, resolve_language


@dataclass
class LiveResult:
    status: str
    content: str
    provider: str
    model: str | None
    response_language: str
    profile: str
    error: str | None = None


class LiveIntelligence:
    def __init__(self) -> None:
        self.provider = (settings.AI_PROVIDER or "").strip().lower()
        self.base = (settings.AI_BASE_URL or "").strip().rstrip("/")
        self.ai_key = (settings.AI_API_KEY or "").strip()
        self.openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip()
        self.timeout = max(10, min(int(settings.AI_TIMEOUT_SECONDS or 30), 90))

    def profile(self, task: str, question: str) -> str:
        text = (question or "").lower()
        if task == "report_factory" or any(x in text for x in ("report", "pdf", "memo", "brief", "packet", "audit", "document")):
            return "report"
        clean = text.strip(" ?!.,")
        if len(question.split()) <= 5 and any(clean == x or clean.startswith(x + " ") for x in ("hi", "hello", "hey", "bonjour", "hola", "salut", "olá", "ola")):
            return "fast"
        return "reasoning"

    def remote(self) -> tuple[str, str, str] | None:
        p = self.provider
        if p in {"openrouter", "openrouter.ai"}:
            key = self.ai_key or self.openrouter_key
            return ((self.base or "https://openrouter.ai/api/v1"), key, "openrouter") if key else None
        if "openrouter.ai" in self.base.lower():
            key = self.ai_key or self.openrouter_key
            return (self.base, key, "openrouter") if key else None
        if p in {"openai", "openai-compatible", "openai_compatible"} and self.base and self.ai_key:
            return self.base, self.ai_key, "openai_compatible"
        if p == "ollama" and self.openrouter_key:
            return "https://openrouter.ai/api/v1", self.openrouter_key, "openrouter"
        return None

    def models(self, profile: str, remote_provider: str) -> list[str]:
        reasoning = (settings.AI_REASONING_MODEL or settings.AI_MODEL or "").strip() or "z-ai/glm-5.2"
        fast = (settings.AI_FAST_MODEL or "").strip() or "qwen/qwen3-next-80b-a3b-instruct"
        report = (settings.AI_REPORT_MODEL or "").strip() or "qwen/qwen3-max"
        primary = report if profile == "report" else fast if profile == "fast" else reasoning
        configured = [x.strip() for x in (settings.AI_MODEL_FALLBACKS or "").split(",") if x.strip()]
        defaults = ["z-ai/glm-5.2", "qwen/qwen3-max", "z-ai/glm-5-turbo", "z-ai/glm-4.5-air", "qwen/qwen3-next-80b-a3b-instruct"] if remote_provider == "openrouter" else []
        out: list[str] = []
        for model in [primary, settings.AI_MODEL, *configured, *defaults]:
            value = (model or "").strip()
            if value and value not in out:
                out.append(value)
        return out

    def ollama_model(self) -> str | None:
        if self.provider != "ollama" or not self.base:
            return None
        model = self.local_model or (settings.AI_MODEL or "").strip()
        return model if model and "/" not in model else None

    @staticmethod
    def content(body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            return ""
        value = (choices[0].get("message") or {}).get("content")
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(str(item.get("text") or item.get("content") or item) if isinstance(item, dict) else str(item) for item in value).strip()
        return ""

    async def run_remote(self, cfg: tuple[str, str, str], models: list[str], messages: list[dict[str, str]], profile: str) -> tuple[str, str] | None:
        endpoint, key, provider = cfg
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"
        tokens = 3200 if profile == "report" else 2200 if profile == "reasoning" else 900
        timeout = 55 if profile == "report" else 38 if profile == "reasoning" else 20
        async with httpx.AsyncClient(timeout=max(8, min(timeout, self.timeout + 25))) as client:
            for model in models[:7]:
                try:
                    response = await client.post(f"{endpoint}/chat/completions", headers=headers, json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": tokens})
                    if response.status_code in {401, 403}:
                        return None
                    if response.status_code >= 400:
                        continue
                    answer = self.content(response.json())
                    if answer:
                        return answer, model
                except (httpx.HTTPError, ValueError, KeyError):
                    continue
        return None

    async def run_local(self, model: str, messages: list[dict[str, str]], profile: str) -> tuple[str, str] | None:
        payload = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": "45m", "options": {"temperature": 0.2, "num_predict": 2800 if profile == "report" else 1900 if profile == "reasoning" else 700, "num_ctx": 8192 if profile != "fast" else 4096}}
        try:
            async with httpx.AsyncClient(timeout=max(20, min(self.timeout + 35, 90))) as client:
                response = await client.post(f"{self.base}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            answer = str((body.get("message") or {}).get("content") or body.get("response") or "").strip()
            return (answer, model) if answer else None
        except (httpx.HTTPError, ValueError, KeyError):
            return None

    async def repair(self, cfg: tuple[str, str, str], model: str, answer: str, code: str, name: str) -> str | None:
        if language_matches_target(answer, code):
            return answer
        request = [
            {
                "role": "system",
                "content": (
                    f"Rewrite this exact answer in {name}. Preserve facts, uncertainty, "
                    "numbers, units, citations, and meaning. Add nothing. Remove nothing. "
                    "Return only the rewritten answer."
                ),
            },
            {"role": "user", "content": answer[:8000]},
        ]
        result = await self.run_remote(cfg, [model], request, "fast")
        if result and language_matches_target(result[0], code):
            return result[0]
        return None

    async def run(self, task: str, question: str, messages: list[dict[str, str]], preferred_language: str | None) -> LiveResult:
        language = resolve_language(preferred_language, question)
        profile = self.profile(task, question)
        system = {"role": "system", "content": "You are AGRO-AI, a high-capability agriculture operations intelligence assistant. Answer the exact current question. Do not use a fixed response template. Use prior turns as context, not as text to repeat. Use workspace evidence only when relevant. Adapt depth and structure to the request. Never invent telemetry, acreage, water use, integrations, compliance status, savings, or customer facts. If a numeric recommendation lacks evidence, explain exactly what is missing and why it matters. " + language.instruction}
        prepared = [system, *[dict(x) for x in messages if x.get("role") != "system"]]
        remote = self.remote()
        local_model = self.ollama_model()

        if self.provider == "ollama" and local_model:
            local = await self.run_local(local_model, prepared, profile)
            if local:
                answer, model = local
                if remote:
                    repaired = await self.repair(remote, self.models(profile, remote[2])[0], answer, language.response_code, language.response_name)
                    if repaired is None:
                        return LiveResult("language_generation_failed", "", "ollama", model, language.response_code, profile, "Model output did not match the requested response language and repair failed.")
                    answer = repaired
                return LiveResult("ok", answer, "ollama", model, language.response_code, profile)

        if remote:
            result = await self.run_remote(remote, self.models(profile, remote[2]), prepared, profile)
            if result:
                answer, model = result
                repaired = await self.repair(remote, model, answer, language.response_code, language.response_name)
                if repaired is None:
                    return LiveResult("language_generation_failed", "", remote[2], model, language.response_code, profile, "Model output did not match the requested response language and repair failed.")
                answer = repaired
                return LiveResult("ok", answer, remote[2], model, language.response_code, profile)

        return LiveResult("unavailable", "", remote[2] if remote else self.provider or "unconfigured", None, language.response_code, profile, "No live model provider completed the request.")

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.services.language import looks_english, resolve_language


DEFAULT_REASONING_MODEL = "z-ai/glm-5.2"
DEFAULT_FAST_MODEL = "qwen/qwen3-next-80b-a3b-instruct"
DEFAULT_REPORT_MODEL = "qwen/qwen3-max"
DEFAULT_REMOTE_FALLBACKS = [
    "z-ai/glm-5.2",
    "qwen/qwen3-max",
    "z-ai/glm-5-turbo",
    "z-ai/glm-4.5-air",
    "qwen/qwen3-next-80b-a3b-instruct",
    "deepseek/deepseek-v3.1-terminus",
]


@dataclass
class AdaptiveChatResult:
    status: str
    content: str
    provider: str
    model: str | None
    response_language: str
    profile: str
    attempts: list[str]
    error: str | None = None


class AdaptiveChatEngine:
    """Live, request-adaptive chat engine with cross-provider failover.

    The engine deliberately returns no fabricated canned answer. If every live
    model path fails, callers receive status='unavailable' and can surface a
    truthful retry state instead of pretending intelligence happened.
    """

    def __init__(self) -> None:
        self.raw_provider = (settings.AI_PROVIDER or "").strip().lower()
        self.configured_base_url = (settings.AI_BASE_URL or "").strip().rstrip("/")
        self.remote_key = (os.getenv("OPENROUTER_API_KEY") or settings.AI_API_KEY or "").strip()
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip()
        self.timeout = max(10, min(int(settings.AI_TIMEOUT_SECONDS or 30), 90))

    def _profile(self, task: str, question: str) -> str:
        text = (question or "").lower()
        report_terms = ("report", "pdf", "memo", "brief", "packet", "analysis", "audit", "compliance")
        complex_terms = ("why", "compare", "diagnose", "strategy", "decision", "calculate", "recommend", "evidence", "risk", "plan")
        if task == "report_factory" or any(term in text for term in report_terms):
            return "report"
        if any(term in text for term in complex_terms) or len(question.split()) > 18:
            return "reasoning"
        # Ask AGRO-AI should default to the serious reasoning profile. Only very
        # small greetings use the faster model.
        if len(question.split()) <= 5 and any(term in text for term in ("hi", "hello", "hey", "bonjour", "hola", "salut")):
            return "fast"
        return "reasoning"

    def _model_candidates(self, profile: str) -> list[str]:
        reasoning = (settings.AI_REASONING_MODEL or settings.AI_MODEL or "").strip() or DEFAULT_REASONING_MODEL
        fast = (settings.AI_FAST_MODEL or "").strip() or DEFAULT_FAST_MODEL
        report = (settings.AI_REPORT_MODEL or "").strip() or DEFAULT_REPORT_MODEL
        primary = report if profile == "report" else fast if profile == "fast" else reasoning
        configured_fallbacks = [item.strip() for item in (settings.AI_MODEL_FALLBACKS or "").split(",") if item.strip()]
        ordered: list[str] = []
        for model in [primary, settings.AI_MODEL, reasoning, report, fast, *configured_fallbacks, *DEFAULT_REMOTE_FALLBACKS]:
            clean = (model or "").strip()
            if clean and clean not in ordered:
                ordered.append(clean)
        return ordered

    def _remote_endpoint(self, models: list[str]) -> str | None:
        if not self.remote_key:
            return None
        base = self.configured_base_url
        provider_is_remote = self.raw_provider in {"openrouter", "openrouter.ai", "openai", "openai-compatible", "openai_compatible"}
        configured_looks_local = any(token in base.lower() for token in ("localhost", "127.0.0.1", ":11434", "/api/chat"))
        remote_model_ids = any("/" in model for model in models)
        if provider_is_remote and base:
            return base
        if base and not configured_looks_local and self.raw_provider != "ollama":
            return base
        # Important production repair: a stale AI_PROVIDER=ollama must not force
        # OpenRouter-style model ids such as z-ai/glm-5.2 through /api/chat.
        if os.getenv("OPENROUTER_API_KEY") or remote_model_ids:
            return "https://openrouter.ai/api/v1"
        return None

    def _headers(self, endpoint: str) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.remote_key}", "Content-Type": "application/json"}
        if "openrouter.ai" in endpoint.lower():
            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"
        return headers

    @staticmethod
    def _extract_content(body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        value = message.get("content")
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    candidate = item.get("text") or item.get("content")
                    if isinstance(candidate, str):
                        parts.append(candidate)
            return "\n".join(parts).strip()
        return ""

    async def _run_remote(self, endpoint: str, models: list[str], messages: list[dict[str, str]], profile: str, attempts: list[str]) -> tuple[str, str] | None:
        timeout = 48 if profile == "report" else 34 if profile == "reasoning" else 20
        max_tokens = 2800 if profile == "report" else 1800 if profile == "reasoning" else 900
        headers = self._headers(endpoint)
        async with httpx.AsyncClient(timeout=max(8, min(timeout, self.timeout + 20))) as client:
            for model in models[:6]:
                payload = {"model": model, "messages": messages, "temperature": 0.22 if profile != "fast" else 0.28, "max_tokens": max_tokens}
                try:
                    response = await client.post(f"{endpoint.rstrip('/')}/chat/completions", headers=headers, json=payload)
                    attempts.append(f"remote:{model}:http_{response.status_code}")
                    if response.status_code in {401, 403}:
                        return None
                    if response.status_code >= 400:
                        continue
                    body = response.json()
                    content = self._extract_content(body)
                    if content:
                        return content, model
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    attempts.append(f"remote:{model}:{exc.__class__.__name__}")
                    continue
        return None

    async def _run_local(self, messages: list[dict[str, str]], profile: str, attempts: list[str]) -> tuple[str, str] | None:
        if self.raw_provider != "ollama" or not self.configured_base_url:
            return None
        model = self.local_model or ((settings.AI_MODEL or "").strip() if "/" not in (settings.AI_MODEL or "") else "")
        if not model:
            attempts.append("ollama:no_compatible_local_model")
            return None
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "45m",
            "options": {
                "temperature": 0.2,
                "num_predict": 2400 if profile == "report" else 1500 if profile == "reasoning" else 700,
                "num_ctx": 8192 if profile != "fast" else 4096,
                "top_p": 0.9,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=max(15, min(self.timeout + 30, 90))) as client:
                response = await client.post(f"{self.configured_base_url}/api/chat", json=payload)
                attempts.append(f"ollama:{model}:http_{response.status_code}")
                response.raise_for_status()
                body = response.json()
            message = body.get("message") or {}
            content = str(message.get("content") or body.get("response") or "").strip()
            return (content, model) if content else None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            attempts.append(f"ollama:{model}:{exc.__class__.__name__}")
            return None

    async def run(self, *, task: str, question: str, messages: list[dict[str, str]], preferred_language: str | None) -> AdaptiveChatResult:
        language = resolve_language(preferred_language, question)
        profile = self._profile(task, question)
        models = self._model_candidates(profile)
        attempts: list[str] = []

        # Keep the exact conversation and make language/anti-canned behavior a
        # hard system constraint without imposing a response template.
        system = {
            "role": "system",
            "content": (
                "You are AGRO-AI, a high-capability agriculture operations intelligence assistant. "
                "Answer the user's exact question; do not substitute a generic capability statement. "
                "Use conversation history and workspace evidence when provided. Adapt depth, structure, and tone to the request. "
                "Do not reuse a prior answer unless the user explicitly asks you to repeat it. "
                "Never invent telemetry, acreage, water use, integrations, compliance status, savings, or customer facts. "
                "Separate known evidence from assumptions when that distinction matters. "
                + language.instruction
            ),
        }
        prepared = [system, *[dict(item) for item in messages if item.get("role") != "system"]]

        endpoint = self._remote_endpoint(models)
        remote = await self._run_remote(endpoint, models, prepared, profile, attempts) if endpoint else None
        if remote:
            content, model = remote
            content = await self._repair_language_if_needed(endpoint, model, content, language.response_code, language.response_name, attempts)
            return AdaptiveChatResult("ok", content, "openrouter" if "openrouter.ai" in endpoint else "openai_compatible", model, language.response_code, profile, attempts)

        local = await self._run_local(prepared, profile, attempts)
        if local:
            content, model = local
            return AdaptiveChatResult("ok", content, "ollama", model, language.response_code, profile, attempts)

        return AdaptiveChatResult("unavailable", "", self.raw_provider or "unconfigured", None, language.response_code, profile, attempts, error="No live model provider completed the request.")

    async def _repair_language_if_needed(self, endpoint: str, model: str, content: str, response_code: str, response_name: str, attempts: list[str]) -> str:
        if response_code == "en" or not looks_english(content):
            return content
        repair_messages = [
            {"role": "system", "content": f"Rewrite the supplied answer in {response_name}. Preserve meaning and facts exactly. Do not add information. Return only the rewritten answer."},
            {"role": "user", "content": content[:7000]},
        ]
        repaired = await self._run_remote(endpoint, [model, *DEFAULT_REMOTE_FALLBACKS], repair_messages, "fast", attempts)
        if repaired and repaired[0].strip():
            return repaired[0].strip()
        return content

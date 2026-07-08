from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.services.language import language_matches_target, resolve_language
from app.services.operational_invariants import check_operational_invariants


_TEST_ROUTE_ALIASES = {
    "auto": "auto",
    "local": "local",
    "edge": "edge",
    "glm": "glm",
    "primary": "primary",
    "deepseek": "challenger",
    "challenger": "challenger",
    "free": "free",
}
_VALID_ROUTING_MODES = {
    "hybrid",
    "remote_first",
    "edge_first",
    "local_first",
    "remote_only",
    "edge_only",
    "local_only",
}


@dataclass
class LiveResult:
    status: str
    content: str
    provider: str
    model: str | None
    response_language: str
    profile: str
    error: str | None = None


def _dedupe(values: list[str | None]) -> list[str]:
    output: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def _ollama_compatible_answer(body: dict[str, Any]) -> str:
    """Extract customer text from real Ollama or the edge Ollama-compatible wrapper."""
    if not isinstance(body, dict):
        return ""
    value = (body.get("message") or {}).get("content") or body.get("response") or ""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if isinstance(parsed, dict):
        for key in ("answer", "summary", "content", "message"):
            item = parsed.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return text


class LiveIntelligence:
    def __init__(self) -> None:
        self.provider = (settings.AI_PROVIDER or "").strip().lower()
        self.base = (settings.AI_BASE_URL or "").strip().rstrip("/")
        self.ai_key = (settings.AI_API_KEY or "").strip()
        self.openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()

        explicit_local_base = (settings.AI_LOCAL_BASE_URL or "").strip().rstrip("/")
        explicit_edge_base = (settings.AI_EDGE_BASE_URL or "").strip().rstrip("/")
        legacy_edge_base = (
            self.base
            if self.provider == "ollama" and "local-ai.agroai-pilot.com" in self.base.lower()
            else ""
        )
        # The production local-ai hostname is currently a Cloudflare Workers AI
        # Ollama-compatible origin, not the Mac. Treat it as edge truthfully.
        self.edge_base = explicit_edge_base or legacy_edge_base
        # Backwards-compatible local fallback only when AI_BASE_URL is an Ollama
        # deployment that is not the known Workers AI hostname.
        self.local_base = explicit_local_base or (
            self.base if self.provider == "ollama" and self.base and not self.edge_base else ""
        )
        self.local_model = (settings.AI_LOCAL_MODEL or "").strip()
        self.edge_model = (settings.AI_EDGE_MODEL or "").strip() or "@cf/zai-org/glm-4.7-flash"
        self.challenger_model = (settings.AI_CHALLENGER_MODEL or "").strip() or "deepseek/deepseek-v4-pro"
        self.free_model = (settings.AI_FREE_MODEL or "").strip()

        configured_mode = (settings.AI_ROUTING_MODE or "hybrid").strip().lower()
        self.routing_mode = configured_mode if configured_mode in _VALID_ROUTING_MODES else "hybrid"
        self.test_commands_enabled = bool(settings.AI_MODEL_TEST_COMMANDS_ENABLED)

        self.local_num_ctx = max(2048, min(int(settings.AI_LOCAL_NUM_CTX or 6144), 16384))
        self.local_max_tokens = max(200, min(int(settings.AI_LOCAL_MAX_TOKENS or 1200), 2800))
        self.local_timeout = max(30, min(int(settings.AI_LOCAL_TIMEOUT_SECONDS or 90), 180))
        self.local_thinking = bool(settings.AI_LOCAL_THINKING)
        self.edge_timeout = max(10, min(int(settings.AI_EDGE_TIMEOUT_SECONDS or 45), 90))
        self.timeout = max(10, min(int(settings.AI_TIMEOUT_SECONDS or 30), 90))

    def profile(self, task: str, question: str) -> str:
        text = (question or "").lower()
        if task == "deep_analysis":
            return "deep"
        if task in {"chat_fast", "quick_chat"}:
            return "fast"
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
        # Local/edge deployments can still use OpenRouter as the hosted frontier lane.
        if p == "ollama":
            key = self.openrouter_key or self.ai_key
            return ("https://openrouter.ai/api/v1", key, "openrouter") if key else None
        return None

    def models(self, profile: str, remote_provider: str, route: str = "auto") -> list[str]:
        reasoning = (settings.AI_REASONING_MODEL or settings.AI_MODEL or "").strip() or "z-ai/glm-5.2"
        fast = (settings.AI_FAST_MODEL or "").strip() or "qwen/qwen3.5-flash-02-23"
        report = (settings.AI_REPORT_MODEL or "").strip() or reasoning
        primary = report if profile == "report" else fast if profile == "fast" else reasoning
        configured = [x.strip() for x in (settings.AI_MODEL_FALLBACKS or "").split(",") if x.strip()]
        defaults = [
            "z-ai/glm-5.2",
            "deepseek/deepseek-v4-pro",
            "qwen/qwen3.5-flash-02-23",
            "z-ai/glm-5-turbo",
            "z-ai/glm-4.5-air",
        ] if remote_provider == "openrouter" else []

        if route == "glm":
            return _dedupe([reasoning])
        if route == "primary":
            return _dedupe([primary])
        if route == "challenger":
            return _dedupe([self.challenger_model])
        if route == "free":
            return _dedupe([self.free_model])

        return _dedupe([
            primary,
            self.challenger_model,
            self.free_model,
            settings.AI_MODEL,
            *configured,
            *defaults,
        ])

    def ollama_model(self) -> str | None:
        model = self.local_model or (
            (settings.AI_MODEL or "").strip()
            if self.provider == "ollama" and "/" not in (settings.AI_MODEL or "")
            else ""
        )
        return model if self.local_base and model and "/" not in model else None

    def edge(self) -> tuple[str, str] | None:
        return (self.edge_base, self.edge_model) if self.edge_base and self.edge_model else None

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

    @staticmethod
    def remote_temperature(model: str, profile: str) -> float:
        normalized = (model or "").lower()
        if normalized.startswith("z-ai/glm-5.2") or normalized.startswith("deepseek/deepseek-v4"):
            return 1.0
        return 0.15 if profile == "deep" else 0.2

    async def run_remote(self, cfg: tuple[str, str, str], models: list[str], messages: list[dict[str, str]], profile: str) -> tuple[str, str] | None:
        endpoint, key, provider = cfg
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"
        tokens = 4200 if profile == "deep" else 3200 if profile == "report" else 2200 if profile == "reasoning" else 900
        timeout = 58 if profile == "deep" else 55 if profile == "report" else 38 if profile == "reasoning" else 20
        async with httpx.AsyncClient(timeout=max(8, min(timeout, self.timeout + 30))) as client:
            for model in models[:8]:
                try:
                    response = await client.post(
                        f"{endpoint}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": self.remote_temperature(model, profile),
                            "max_tokens": tokens,
                        },
                    )
                    # Authentication and account-credit failures are account-wide.
                    # Do not burn latency retrying the same broken account across eight models.
                    if response.status_code in {401, 402, 403}:
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
        if not self.local_base:
            return None
        if profile == "fast":
            num_predict = min(self.local_max_tokens, 600)
            num_ctx = min(self.local_num_ctx, 4096)
        elif profile == "deep":
            num_predict = min(max(self.local_max_tokens, 1200), 1800)
            num_ctx = min(max(self.local_num_ctx, 8192), 12288)
        elif profile == "report":
            num_predict = min(max(self.local_max_tokens, 1000), 1600)
            num_ctx = min(max(self.local_num_ctx, 6144), 8192)
        else:
            num_predict = self.local_max_tokens
            num_ctx = self.local_num_ctx

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": self.local_thinking and profile == "deep",
            "keep_alive": "45m",
            "options": {
                "temperature": 0.15 if profile == "deep" else 0.2,
                "num_predict": num_predict,
                "num_ctx": num_ctx,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.local_timeout) as client:
                response = await client.post(f"{self.local_base}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            answer = _ollama_compatible_answer(body)
            return (answer, model) if answer else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    async def run_edge(self, cfg: tuple[str, str], messages: list[dict[str, str]], profile: str) -> tuple[str, str] | None:
        base_url, model = cfg
        max_tokens = 2200 if profile == "deep" else 1800 if profile == "report" else 1400 if profile == "reasoning" else 700
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.15 if profile == "deep" else 0.2,
                "num_predict": max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.edge_timeout) as client:
                response = await client.post(f"{base_url}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            answer = _ollama_compatible_answer(body)
            return (answer, model) if answer else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
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
            invariant_check = check_operational_invariants(answer, result[0])
            if invariant_check.ok:
                return result[0]
        return None

    def parse_test_route(self, question: str) -> tuple[str, str]:
        if not self.test_commands_enabled:
            return "auto", question
        match = re.match(r"^\s*/(auto|local|edge|glm|primary|deepseek|challenger|free)\b\s*", question or "", flags=re.IGNORECASE)
        if not match:
            return "auto", question
        alias = match.group(1).lower()
        clean = (question[match.end():] or "").strip()
        return _TEST_ROUTE_ALIASES[alias], clean or question

    @staticmethod
    def rewrite_question(messages: list[dict[str, str]], original: str, clean: str) -> list[dict[str, str]]:
        if not original or original == clean:
            return [dict(item) for item in messages]
        rewritten: list[dict[str, str]] = []
        for item in messages:
            copy = dict(item)
            content = str(copy.get("content") or "")
            if original in content:
                copy["content"] = content.replace(original, clean, 1)
            rewritten.append(copy)
        return rewritten

    async def finish_remote(
        self,
        cfg: tuple[str, str, str],
        answer: str,
        model: str,
        response_code: str,
        response_name: str,
        profile: str,
    ) -> LiveResult:
        repaired = await self.repair(cfg, model, answer, response_code, response_name)
        if repaired is None:
            return LiveResult(
                "language_generation_failed",
                "",
                cfg[2],
                model,
                response_code,
                profile,
                "Model output did not match the requested response language and repair failed.",
            )
        return LiveResult("ok", repaired, cfg[2], model, response_code, profile)

    async def finish_lane(
        self,
        answer: str,
        model: str,
        provider: str,
        response_code: str,
        response_name: str,
        profile: str,
        remote: tuple[str, str, str] | None,
        *,
        allow_remote_repair: bool,
    ) -> LiveResult:
        if language_matches_target(answer, response_code):
            return LiveResult("ok", answer, provider, model, response_code, profile)
        if allow_remote_repair and remote:
            repair_models = self.models(profile, remote[2], "auto")
            if repair_models:
                repaired = await self.repair(remote, repair_models[0], answer, response_code, response_name)
                if repaired is not None:
                    return LiveResult("ok", repaired, provider, model, response_code, profile)
        return LiveResult(
            "language_generation_failed",
            "",
            provider,
            model,
            response_code,
            profile,
            "Model output did not match the requested response language and repair failed.",
        )

    def auto_order(self, profile: str) -> list[str]:
        if self.routing_mode == "remote_only":
            return ["remote"]
        if self.routing_mode == "edge_only":
            return ["edge"]
        if self.routing_mode == "local_only":
            return ["local"]
        if self.routing_mode == "remote_first":
            return ["remote", "edge", "local"]
        if self.routing_mode == "edge_first":
            return ["edge", "remote", "local"]
        if self.routing_mode == "local_first":
            return ["local", "edge", "remote"]
        # Hybrid: low-latency always-on edge for quick chat; frontier first for
        # reasoning/report/deep work; actual Mac Ollama remains a last-resort lane.
        return ["edge", "local", "remote"] if profile == "fast" else ["remote", "edge", "local"]

    async def run(self, task: str, question: str, messages: list[dict[str, str]], preferred_language: str | None) -> LiveResult:
        route, clean_question = self.parse_test_route(question)
        language = resolve_language(preferred_language, clean_question)
        profile = self.profile(task, clean_question)
        deep_instruction = " For Deep analysis, inspect assumptions, conflicting evidence, missing evidence, second-order effects, operational tradeoffs, and plausible failure modes before concluding." if profile == "deep" else ""
        system = {
            "role": "system",
            "content": "You are AGRO-AI, a high-capability agriculture operations intelligence assistant. Answer the exact current question. Do not use a fixed response template. Use prior turns as context, not as text to repeat. Use workspace evidence only when relevant. Adapt depth and structure to the request. Never invent telemetry, acreage, water use, integrations, compliance status, savings, or customer facts. If a numeric recommendation lacks evidence, explain exactly what is missing and why it matters." + deep_instruction + " " + language.instruction,
        }
        rewritten_messages = self.rewrite_question(messages, question, clean_question)
        prepared = [system, *[dict(x) for x in rewritten_messages if x.get("role") != "system"]]
        remote = self.remote()
        local_model = self.ollama_model()
        edge = self.edge()

        if route == "local":
            if not local_model:
                return LiveResult("unavailable", "", "ollama", None, language.response_code, profile, "No actual local Ollama origin and model are configured.")
            local = await self.run_local(local_model, prepared, profile)
            if not local:
                return LiveResult("unavailable", "", "ollama", local_model, language.response_code, profile, "The forced local model did not complete the request.")
            return await self.finish_lane(local[0], local[1], "ollama", language.response_code, language.response_name, profile, remote, allow_remote_repair=False)

        if route == "edge":
            if not edge:
                return LiveResult("unavailable", "", "cloudflare_workers_ai", None, language.response_code, profile, "No edge AI origin is configured.")
            edge_result = await self.run_edge(edge, prepared, profile)
            if not edge_result:
                return LiveResult("unavailable", "", "cloudflare_workers_ai", edge[1], language.response_code, profile, "The forced edge model did not complete the request.")
            return await self.finish_lane(edge_result[0], edge_result[1], "cloudflare_workers_ai", language.response_code, language.response_name, profile, remote, allow_remote_repair=False)

        if route in {"glm", "primary", "challenger", "free"}:
            if not remote:
                return LiveResult("unavailable", "", "openrouter", None, language.response_code, profile, f"The forced {route} route requires a configured remote provider.")
            candidates = self.models(profile, remote[2], route)
            if not candidates:
                return LiveResult("unavailable", "", remote[2], None, language.response_code, profile, f"No model is configured for the forced {route} route.")
            result = await self.run_remote(remote, candidates, prepared, profile)
            if not result:
                return LiveResult("unavailable", "", remote[2], candidates[0], language.response_code, profile, f"The forced {route} model did not complete the request.")
            return await self.finish_remote(remote, result[0], result[1], language.response_code, language.response_name, profile)

        last_failure: LiveResult | None = None
        for lane in self.auto_order(profile):
            if lane == "remote" and remote:
                candidates = self.models(profile, remote[2], "auto")
                if candidates:
                    result = await self.run_remote(remote, candidates, prepared, profile)
                    if result:
                        finished = await self.finish_remote(remote, result[0], result[1], language.response_code, language.response_name, profile)
                        if finished.status == "ok":
                            return finished
                        last_failure = finished
            if lane == "edge" and edge:
                edge_result = await self.run_edge(edge, prepared, profile)
                if edge_result:
                    finished = await self.finish_lane(edge_result[0], edge_result[1], "cloudflare_workers_ai", language.response_code, language.response_name, profile, remote, allow_remote_repair=True)
                    if finished.status == "ok":
                        return finished
                    last_failure = finished
            if lane == "local" and local_model:
                local = await self.run_local(local_model, prepared, profile)
                if local:
                    finished = await self.finish_lane(local[0], local[1], "ollama", language.response_code, language.response_name, profile, remote, allow_remote_repair=True)
                    if finished.status == "ok":
                        return finished
                    last_failure = finished

        if last_failure is not None:
            return last_failure
        provider = remote[2] if remote else "cloudflare_workers_ai" if edge else "ollama" if local_model else self.provider or "unconfigured"
        return LiveResult("unavailable", "", provider, None, language.response_code, profile, "No live model provider completed the request.")

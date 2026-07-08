from __future__ import annotations

import logging
import os
from typing import Iterable

import httpx

from app.core.config import settings
from app.services.language import language_matches_target, resolve_language
from app.services.live_intelligence import LiveIntelligence, LiveResult


logger = logging.getLogger(__name__)

_DEFAULT_EDGE_BASE = "https://local-ai.agroai-pilot.com"
_DEFAULT_EDGE_MODEL = "@cf/zai-org/glm-4.7-flash"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _dedupe(values: Iterable[str | None]) -> list[str]:
    output: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def _is_free_model(model: str) -> bool:
    value = (model or "").strip().lower()
    return value.endswith(":free") or "/free" in value


def _openrouter_key() -> str:
    return str(os.getenv("OPENROUTER_API_KEY") or settings.AI_API_KEY or "").strip()


def _openrouter_models(profile: str) -> list[str]:
    reasoning = str(settings.AI_REASONING_MODEL or settings.AI_MODEL or "").strip()
    report = str(settings.AI_REPORT_MODEL or reasoning or "").strip()
    fast = str(settings.AI_FAST_MODEL or "").strip()
    free = str(settings.AI_FREE_MODEL or "").strip()
    challenger = str(settings.AI_CHALLENGER_MODEL or "").strip()
    configured = [
        item.strip()
        for item in str(settings.AI_MODEL_FALLBACKS or "").split(",")
        if item.strip()
    ]
    primary = report if profile == "report" else fast if profile == "fast" else reasoning

    # A zero-price route must be tried before paid routes after the primary runtime
    # has already failed. The previous implementation stopped the whole hosted lane
    # on HTTP 402 and therefore never reached AI_FREE_MODEL.
    return _dedupe([
        free,
        primary,
        challenger,
        settings.AI_MODEL,
        *configured,
    ])


def _message_content(body: dict) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    value = message.get("content")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text") or item.get("content") or item)
            if isinstance(item, dict)
            else str(item)
            for item in value
        ).strip()
    return ""


async def _run_openrouter(
    *,
    messages: list[dict[str, str]],
    profile: str,
) -> tuple[str, str] | None:
    key = _openrouter_key()
    if not key:
        logger.warning("ai_resilience hosted_unconfigured")
        return None

    models = _openrouter_models(profile)
    if not models:
        logger.warning("ai_resilience hosted_models_empty")
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.APP_URL or "https://app.agroai-pilot.com",
        "X-Title": "AGRO-AI Enterprise Portal",
    }
    max_tokens = 3600 if profile == "report" else 2800 if profile in {"deep", "reasoning"} else 1000
    timeout = 65 if profile in {"deep", "report"} else 45
    paid_blocked = False

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in models[:10]:
            if paid_blocked and not _is_free_model(model):
                continue
            try:
                response = await client.post(
                    f"{_OPENROUTER_BASE}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 1.0 if model.startswith(("z-ai/glm-5", "deepseek/deepseek-v4")) else 0.2,
                        "max_tokens": max_tokens,
                    },
                )
            except httpx.HTTPError as exc:
                logger.warning("ai_resilience hosted_transport model=%s error=%s", model, exc.__class__.__name__)
                continue

            status = response.status_code
            if status in {401, 403}:
                logger.error("ai_resilience hosted_auth_failed status=%s model=%s", status, model)
                return None
            if status == 402:
                # Insufficient credit is not fatal when a configured free model exists.
                paid_blocked = True
                logger.warning("ai_resilience hosted_payment_required model=%s trying_free_fallback=true", model)
                continue
            if status >= 400:
                logger.warning("ai_resilience hosted_http_error status=%s model=%s", status, model)
                continue

            try:
                answer = _message_content(response.json())
            except (ValueError, KeyError, TypeError):
                logger.warning("ai_resilience hosted_invalid_json model=%s", model)
                continue
            if answer:
                return answer, model

    return None


async def _run_edge(
    *,
    messages: list[dict[str, str]],
    profile: str,
) -> tuple[str, str] | None:
    base = str(settings.AI_EDGE_BASE_URL or "").strip().rstrip("/") or _DEFAULT_EDGE_BASE
    model = str(settings.AI_EDGE_MODEL or "").strip() or _DEFAULT_EDGE_MODEL
    token = str(settings.AI_EDGE_AUTH_TOKEN or "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    num_predict = 2000 if profile in {"deep", "report"} else 1400 if profile == "reasoning" else 700

    try:
        async with httpx.AsyncClient(timeout=max(20, int(settings.AI_EDGE_TIMEOUT_SECONDS or 45))) as client:
            response = await client.post(
                f"{base}/api/chat",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.2, "num_predict": num_predict},
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("ai_resilience edge_transport error=%s", exc.__class__.__name__)
        return None

    if response.status_code >= 400:
        logger.warning("ai_resilience edge_http_error status=%s", response.status_code)
        return None

    try:
        body = response.json()
        value = (body.get("message") or {}).get("content") or body.get("response") or ""
        answer = str(value or "").strip()
        if answer.startswith("{"):
            import json

            try:
                parsed = json.loads(answer)
                if isinstance(parsed, dict):
                    answer = str(parsed.get("answer") or parsed.get("summary") or answer).strip()
            except json.JSONDecodeError:
                pass
    except (ValueError, KeyError, TypeError):
        logger.warning("ai_resilience edge_invalid_json")
        return None

    return (answer, model) if answer else None


async def run_resilient_intelligence(
    *,
    task: str,
    question: str,
    messages: list[dict[str, str]],
    preferred_language: str | None,
) -> LiveResult:
    """Run the normal router, then recover through independent provider paths.

    This is intentionally provider-independent. It protects production from a
    wrong AI_BASE_URL/AI_PROVIDER pairing, an OpenRouter 402 that previously
    skipped free routes, and a missing AI_EDGE_BASE_URL on a Render service.
    """
    runtime = LiveIntelligence()
    first = await runtime.run(task, question, messages, preferred_language)
    if first.status == "ok" and first.content.strip():
        return first

    language = resolve_language(preferred_language, question)
    profile = runtime.profile(task, question)

    # First independent recovery lane: always-on AGRO-AI edge origin. This path
    # uses the known production hostname even when Render missed AI_EDGE_BASE_URL.
    edge = await _run_edge(messages=messages, profile=profile)
    if edge:
        answer, model = edge
        if language_matches_target(answer, language.response_code):
            return LiveResult("ok", answer, "cloudflare_workers_ai", model, language.response_code, profile)

    # Second independent recovery lane: OpenRouter with a free route attempted
    # first, so an unfunded account can still use AI_FREE_MODEL when available.
    hosted = await _run_openrouter(messages=messages, profile=profile)
    if hosted:
        answer, model = hosted
        if language_matches_target(answer, language.response_code):
            return LiveResult("ok", answer, "openrouter", model, language.response_code, profile)

    logger.error(
        "ai_resilience exhausted first_status=%s first_provider=%s first_model=%s",
        first.status,
        first.provider,
        first.model,
    )
    return first

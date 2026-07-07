"""Hosted JSON-preserving fallback for UI catalog translation.

This path is intentionally independent of the primary AI_PROVIDER. AGRO-AI may run
customer chat through local Ollama while still using an already-configured
OpenRouter credential as a resilient translation fallback.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai_gateway import AIGatewayResult

DEFAULT_TRANSLATION_MODEL = "qwen/qwen3-next-80b-a3b-instruct"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _strip_json_fences(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", text).strip()


def _message_content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    value = message.get("content")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                part = item.get("text") or item.get("content")
                if isinstance(part, str):
                    parts.append(part)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def _json_catalog_content(body: Any) -> str:
    raw = _strip_json_fences(_message_content(body))
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("response was not a non-empty JSON object")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _candidate_models() -> list[str]:
    configured = [
        (os.getenv("UI_TRANSLATION_MODEL") or "").strip(),
        (settings.AI_FAST_MODEL or "").strip(),
        DEFAULT_TRANSLATION_MODEL,
    ]
    configured.extend(x.strip() for x in (settings.AI_MODEL_FALLBACKS or "").split(",") if x.strip())
    out: list[str] = []
    for model in configured:
        if model and "/" in model and model not in out:
            out.append(model)
    return out[:5]


async def run_hosted_ui_translation(
    *,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout_seconds: int | None = None,
) -> AIGatewayResult:
    key = (os.getenv("OPENROUTER_API_KEY") or settings.AI_API_KEY or "").strip()
    if not key:
        return AIGatewayResult(
            status="unavailable",
            content="",
            provider="openrouter",
            model=None,
            error="No OpenRouter translation credential configured.",
        )

    base_url = (os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.APP_URL or "https://app.agroai-pilot.com",
        "X-Title": "AGRO-AI Enterprise Portal",
    }
    failures: list[str] = []
    timeout = max(8, min(int(timeout_seconds or 35), 75))

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in _candidate_models():
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": min(float(temperature or 0.0), 0.15),
                "max_tokens": max(256, min(int(max_tokens or 1200), 2200)),
                "response_format": {"type": "json_object"},
            }
            try:
                response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                if response.status_code in {400, 422}:
                    retry_payload = dict(payload)
                    retry_payload.pop("response_format", None)
                    response = await client.post(f"{base_url}/chat/completions", headers=headers, json=retry_payload)
                if response.status_code >= 400:
                    failures.append(f"{model}: HTTP {response.status_code}: {response.text[:300]}")
                    if response.status_code in {401, 403}:
                        break
                    continue
                body = response.json()
                content = _json_catalog_content(body)
                return AIGatewayResult(
                    status="ok",
                    content=content,
                    provider="openrouter",
                    model=model,
                    raw=body if isinstance(body, dict) else {"response": body},
                )
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
                failures.append(f"{model}: {exc}")

    return AIGatewayResult(
        status="unavailable",
        content="",
        provider="openrouter",
        model=None,
        error="Hosted UI translation failed: " + " | ".join(failures),
    )

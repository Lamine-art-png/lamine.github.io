"""Dedicated JSON-preserving UI translation path for local Ollama models."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.services.ai_gateway import AIGatewayResult

LOCAL_TRANSLATION_REVISION = "json-fallback-v2"


def _strip_json_fences(value: str) -> str:
    text = (value or "").strip()
    lower = text.lower()
    if "</think>" in lower:
        text = text[lower.rfind("</think>") + len("</think>"):].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", text).strip()


def _json_content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    message = body.get("message") or {}
    raw = message.get("content") if isinstance(message, dict) else ""
    if not raw:
        raw = body.get("response") or ""
    parsed = json.loads(_strip_json_fences(str(raw)))
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("response was not a non-empty JSON object")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


async def run_local_ui_translation(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout_seconds: int | None = None,
) -> AIGatewayResult:
    base = (base_url or "").strip().rstrip("/")
    selected = (model or "").strip()
    if not base or not selected or "/" in selected:
        return AIGatewayResult(status="unavailable", content="", provider="ollama", model=selected or None, error="No compatible local Ollama translation model configured.")

    options = {
        "temperature": min(float(temperature or 0.0), 0.15),
        "num_predict": max(128, min(int(max_tokens or 900), 1400)),
        "num_ctx": 4096,
        "top_p": 0.9,
    }
    chat_payload: dict[str, Any] = {
        "model": selected,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "45m",
        "options": options,
    }
    prompt = "\n\n".join(f"{str(message.get('role') or 'user').upper()}: {str(message.get('content') or '')}" for message in messages)
    generate_payload: dict[str, Any] = {
        "model": selected,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "45m",
        "options": options,
    }

    failures: list[str] = []
    timeout = max(12, min(int(timeout_seconds or 45), 75))
    async with httpx.AsyncClient(timeout=timeout) as client:
        for path, payload in (("/api/chat", chat_payload), ("/api/generate", generate_payload)):
            try:
                response = await client.post(f"{base}{path}", json=payload)
                if response.status_code >= 400:
                    failures.append(f"{path}: HTTP {response.status_code}: {response.text[:500]}")
                    continue
                body = response.json()
                content = _json_content(body)
                return AIGatewayResult(status="ok", content=content, provider="ollama", model=selected, raw=body if isinstance(body, dict) else {"response": body})
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
                failures.append(f"{path}: {exc}")

    return AIGatewayResult(status="unavailable", content="", provider="ollama", model=selected, error="Local Ollama JSON translation failed: " + " | ".join(failures))

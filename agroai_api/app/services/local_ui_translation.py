"""Dedicated JSON-preserving UI translation path for Ollama-compatible origins."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai_gateway import AIGatewayResult

LOCAL_TRANSLATION_REVISION = "json-fallback-v3"


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


def _is_edge_base(value: str) -> bool:
    base = (value or "").strip().rstrip("/")
    if not base:
        return False
    explicit = (settings.AI_EDGE_BASE_URL or "").strip().rstrip("/")
    if explicit and base == explicit:
        return True
    return "local-ai.agroai-pilot.com" in base.lower()


def _edge_headers(base: str) -> dict[str, str]:
    if not _is_edge_base(base):
        return {}
    token = (settings.AI_EDGE_AUTH_TOKEN or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


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
    edge_compat = _is_edge_base(base)
    if not base or not selected or ("/" in selected and not edge_compat):
        return AIGatewayResult(
            status="unavailable",
            content="",
            provider="cloudflare-workers-ai" if edge_compat else "ollama",
            model=selected or None,
            error="No compatible Ollama translation model configured.",
        )

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

    # The Workers AI compatibility origin exposes /api/chat only. Actual Ollama
    # keeps the /api/generate fallback for older local model behavior.
    attempts: tuple[tuple[str, dict[str, Any]], ...] = (
        (("/api/chat", chat_payload),)
        if edge_compat
        else (("/api/chat", chat_payload), ("/api/generate", generate_payload))
    )
    failures: list[str] = []
    timeout = max(12, min(int(timeout_seconds or 45), 75))
    async with httpx.AsyncClient(timeout=timeout) as client:
        for path, payload in attempts:
            try:
                response = await client.post(
                    f"{base}{path}",
                    headers=_edge_headers(base),
                    json=payload,
                )
                if response.status_code >= 400:
                    failures.append(f"{path}: HTTP {response.status_code}: {response.text[:500]}")
                    continue
                body = response.json()
                content = _json_content(body)
                provider = str(
                    body.get("provider")
                    or ("cloudflare-workers-ai" if edge_compat else "ollama")
                ).strip()
                actual_model = str(body.get("model") or selected).strip()
                return AIGatewayResult(
                    status="ok",
                    content=content,
                    provider=provider,
                    model=actual_model,
                    raw=body if isinstance(body, dict) else {"response": body},
                )
            except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
                failures.append(f"{path}: {exc}")

    provider = "cloudflare-workers-ai" if edge_compat else "ollama"
    return AIGatewayResult(
        status="unavailable",
        content="",
        provider=provider,
        model=selected,
        error="Ollama-compatible JSON translation failed: " + " | ".join(failures),
    )

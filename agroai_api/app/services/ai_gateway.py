"""Provider-agnostic AI gateway for OpenAI-compatible model endpoints."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


@dataclass
class AIGatewayResult:
    status: str
    content: str
    provider: str
    model: str | None
    demo_fallback: bool = False
    raw: dict[str, Any] | None = None
    error: str | None = None


class AIGateway:
    """Thin gateway for OpenAI-compatible chat completions and Ollama."""

    def __init__(self) -> None:
        self.provider = (settings.AI_PROVIDER or "").strip().lower()
        self.base_url = (settings.AI_BASE_URL or "").strip().rstrip("/")
        self.api_key = (settings.AI_API_KEY or "").strip()
        self.model = (settings.AI_MODEL or "").strip()
        self.timeout = settings.AI_TIMEOUT_SECONDS or 30

    @property
    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.base_url and self.model)
        return bool(self.provider and self.base_url and self.model and self.api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> AIGatewayResult:
        if not self.is_configured:
            return self._offline_fallback(messages)

        try:
            if self.provider == "ollama":
                return await self._chat_ollama(messages, temperature)
            return await self._chat_openai_compatible(messages, temperature, response_format)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return AIGatewayResult(
                status="unavailable",
                content=(
                    "AI unavailable: model gateway request failed. No operational "
                    "recommendation was generated."
                ),
                provider=self.provider or "unconfigured",
                model=self.model or None,
                demo_fallback=True,
                error=str(exc),
            )

    async def _chat_openai_compatible(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, Any] | None,
    ) -> AIGatewayResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        return AIGatewayResult(
            status="ok",
            content=content,
            provider=self.provider,
            model=self.model,
            raw=body,
        )

    async def _chat_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AIGatewayResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            body = response.json()

        content = body.get("message", {}).get("content", "")
        return AIGatewayResult(
            status="ok",
            content=content,
            provider="ollama",
            model=self.model,
            raw=body,
        )

    def _offline_fallback(self, messages: list[dict[str, str]]) -> AIGatewayResult:
        user_message = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = json.dumps(
            {
                "status": "unavailable",
                "summary": (
                    "AI unavailable/demo fallback: no model provider is configured, "
                    "so AGRO-AI did not generate a live intelligence result."
                ),
                "request_received": user_message[:500],
                "missing_data": ["AI_PROVIDER", "AI_BASE_URL", "AI_MODEL"],
                "risk_flags": ["No model inference was performed."],
                "next_action": (
                    "Configure an OpenAI-compatible hosted endpoint or local Ollama "
                    "runtime, then retry with verified workspace evidence."
                ),
            }
        )
        return AIGatewayResult(
            status="unavailable",
            content=content,
            provider="offline",
            model=None,
            demo_fallback=True,
        )


def parse_model_json(content: str) -> dict[str, Any]:
    """Parse a model JSON object, tolerating fenced output."""
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"summary": content}
    return value if isinstance(value, dict) else {"result": value}

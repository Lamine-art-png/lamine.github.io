"""Provider-agnostic AI gateway for OpenAI-compatible model endpoints."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


FINAL_ANSWER_PROMPT = """
Return only the final customer-safe JSON answer.
Do not include reasoning, scratchpad, <think>, markdown, or code fences.
Use this exact JSON shape when possible:
{
  "summary": "...",
  "available_data": [],
  "missing_data": [],
  "integration_status": [],
  "recommendations": [],
  "next_actions": [],
  "confidence": "low",
  "customer_safe": true
}
"""

AGRO_AI_OPERATING_CONTEXT = """
You are AGRO-AI's live operating intelligence layer, not a generic chatbot.
AGRO-AI turns fragmented agriculture data into decisions, evidence records, alerts, and enterprise reporting.
The first wedge is irrigation, water-use, compliance, and field operations. The broader product direction is Terris: a field intelligence layer and operating evidence graph for agriculture.
Customers include growers, farm managers, agronomists, irrigation professionals, water agencies, NRDs, districts, lenders, insurers, exporters, and enterprise agriculture teams.
Important source families include John Deere Operations Center, WiseConn, Talgil, controllers, flow meters, ET/weather/OpenET, soil moisture, satellite analytics, field logs, operator notes, CSV/PDF uploads, groundwater, nitrate, chemigation, and customer workspace records.
Always preserve provenance: measured, reported, estimated, inferred, sample, and missing are different.

Your job is to explain what is happening, find missing evidence and contradictions, turn field and water records into recommendations, checklists, assurance packets, reports, and next actions.
Sound natural, calm, direct, and specific. Answer the user's actual question first. Do not repeat the same template. Do not invent live integrations, telemetry, yields, compliance status, savings, or customer facts.
Return valid JSON only. Put the natural answer in summary and answer. Keep arrays concise and operational.
"""


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

    def _with_agroai_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        enriched = [dict(message) for message in messages]
        for message in enriched:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content', '')}\n\n{AGRO_AI_OPERATING_CONTEXT}".strip()
                return enriched
        return [{"role": "system", "content": AGRO_AI_OPERATING_CONTEXT}] + enriched

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
        model_override: str | None = None,
    ) -> AIGatewayResult:
        messages = self._with_agroai_context(messages)
        if not self.is_configured:
            return self._offline_fallback(messages)

        try:
            if self.provider == "ollama":
                if model_override:
                    return await self._chat_ollama(messages, temperature, model_override=model_override)
                return await self._chat_ollama(messages, temperature)
            if model_override:
                return await self._chat_openai_compatible(messages, temperature, response_format, model_override=model_override)
            return await self._chat_openai_compatible(messages, temperature, response_format)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return AIGatewayResult(
                status="unavailable",
                content=json.dumps(
                    {
                        "summary": "I could not reach the live model provider for this request. The workspace evidence layer is still available, but no live model inference was completed.",
                        "available_data": [],
                        "missing_data": ["live model response"],
                        "recommendations": ["Retry once the model provider is reachable."],
                        "next_actions": ["check_model_provider", "retry_with_workspace_context"],
                        "customer_safe": True,
                    }
                ),
                provider=self.provider or "unconfigured",
                model=model_override or self.model or None,
                demo_fallback=True,
                error=str(exc),
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url.lower():
            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"
        return headers

    def _message_content(self, body: dict[str, Any]) -> str:
        message = body["choices"][0].get("message") or {}
        value = message.get("content")
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    piece = item.get("text") or item.get("content")
                    if isinstance(piece, str):
                        parts.append(piece)
            return "\n".join(parts)
        return ""

    async def _post_openai_payload(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        if response.status_code in {400, 422} and "response_format" in payload:
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=retry_payload,
            )
        response.raise_for_status()
        return response.json()

    async def _chat_openai_compatible(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, Any] | None,
        model_override: str | None = None,
    ) -> AIGatewayResult:
        payload: dict[str, Any] = {
            "model": model_override or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2200,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = self._headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            body = await self._post_openai_payload(client, headers, payload)
            raw_content = self._message_content(body)
            content = extract_final_answer(raw_content)

            if not content:
                final_payload = dict(payload)
                final_payload["messages"] = messages + [
                    {"role": "assistant", "content": str(raw_content)[:4000]},
                    {"role": "user", "content": FINAL_ANSWER_PROMPT},
                ]
                final_body = await self._post_openai_payload(client, headers, final_payload)
                final_raw = self._message_content(final_body)
                content = extract_final_answer(final_raw)
                body = {"first_response": body, "final_response": final_body}

        if not content:
            content = json.dumps(
                {
                    "summary": "The model provider returned a response, but not in a customer-safe final format. I need one clean retry with the same workspace context.",
                    "available_data": [],
                    "missing_data": ["customer-safe final model answer"],
                    "integration_status": [],
                    "recommendations": ["Retry with the same workspace context and a stricter final-answer instruction."],
                    "next_actions": ["retry_with_grounded_context"],
                    "confidence": "low",
                    "customer_safe": True,
                }
            )

        return AIGatewayResult(
            status="ok",
            content=content,
            provider=self.provider,
            model=model_override or self.model,
            raw=body,
        )

    async def _chat_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        model_override: str | None = None,
    ) -> AIGatewayResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model_override or self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            body = response.json()

        content = extract_final_answer(body.get("message", {}).get("content", ""))
        return AIGatewayResult(
            status="ok",
            content=content,
            provider="ollama",
            model=model_override or self.model,
            raw=body,
        )

    def _offline_fallback(self, messages: list[dict[str, str]]) -> AIGatewayResult:
        user_message = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = json.dumps(
            {
                "status": "unavailable",
                "summary": "I can see the request, but live inference is not available. I should not pretend to analyze the workspace with a model until the provider is reachable.",
                "request_received": user_message[:500],
                "missing_data": ["live model provider"],
                "risk_flags": ["No live model inference was performed."],
                "recommendations": ["Keep this in safe mode until the hosted model endpoint is reachable."],
                "next_actions": ["configure_model_provider", "retry_with_workspace_context"],
                "customer_safe": True,
            }
        )
        return AIGatewayResult(
            status="unavailable",
            content=content,
            provider="offline",
            model=None,
            demo_fallback=True,
        )


def _strip_markdown_fences(text: str) -> str:
    if text.strip().startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        return "\n".join(lines).strip()
    return text.strip()


def extract_final_answer(content: str) -> str:
    """Return only customer-safe final answer text/JSON."""
    text = (content or "").strip()
    if not text:
        return ""

    lower = text.lower()
    if "</think>" in lower:
        close = lower.rfind("</think>")
        text = text[close + len("</think>") :].strip()
    else:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        if "<think>" in text.lower():
            first_json = text.find("{")
            if first_json >= 0:
                text = text[first_json:].strip()
            else:
                return ""

    text = _strip_markdown_fences(text)

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1].strip()

    blocked_markers = [
        "okay, so i'm",
        "let me think",
        "i need to figure",
        "the user provided",
        "looking at the evidence",
        "i'm trying to figure",
    ]
    low = text.lower()
    if any(marker in low for marker in blocked_markers):
        return ""

    return text.strip()


def sanitize_model_text(content: str) -> str:
    return extract_final_answer(content)


def parse_model_json(content: str) -> dict[str, Any]:
    """Parse a model JSON object, tolerating fenced or prefaced output."""
    text = extract_final_answer(content)
    if not text:
        return {
            "summary": "",
            "available_data": [],
            "missing_data": ["customer-safe model output"],
            "recommended_next_actions": ["retry_with_grounded_context"],
            "confidence": "low",
            "customer_safe": True,
            "_safe_mode": True,
        }

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                value = None
            else:
                if isinstance(value, dict):
                    return value
        return {
            "summary": text,
            "available_data": [],
            "missing_data": ["structured model JSON"],
            "recommended_next_actions": ["review current evidence context", "retry request"],
            "confidence": "low",
            "customer_safe": True,
            "_safe_mode": True,
        }
    if isinstance(value, dict):
        return value
    return {
        "summary": str(value),
        "available_data": [],
        "missing_data": ["structured model JSON object"],
        "recommended_next_actions": ["review current evidence context", "retry request"],
        "confidence": "low",
        "customer_safe": True,
        "_safe_mode": True,
    }

"""Provider-agnostic AI gateway for OpenAI-compatible model endpoints."""
from __future__ import annotations

import json
import os
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
  "answer": "...",
  "work_completed": [],
  "available_data": [],
  "missing_data": [],
  "agent_plan": [],
  "integration_status": [],
  "recommendations": [],
  "next_actions": [],
  "risk_flags": [],
  "confidence": "low|medium|high",
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


def _normalize_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    if provider in {"openrouter", "openrouter.ai", "openai", "openai-compatible", "openai_compatible"}:
        return "openai_compatible"
    return provider


def _normalize_base_url(value: str, provider: str) -> str:
    base_url = (value or "").strip().rstrip("/")
    # Most setup mistakes put the full chat-completions URL in AI_BASE_URL.
    # The gateway appends /chat/completions itself, so normalize that here.
    suffixes = ("/chat/completions", "/completions")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if base_url.lower().endswith(suffix):
                base_url = base_url[: -len(suffix)].rstrip("/")
                changed = True
    if not base_url and provider == "openai_compatible" and (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY")):
        base_url = "https://openrouter.ai/api/v1"
    return base_url


class AIGateway:
    """Thin gateway for OpenAI-compatible chat completions and Ollama."""

    def __init__(self) -> None:
        raw_provider = (settings.AI_PROVIDER or "").strip().lower()
        self.provider = _normalize_provider(raw_provider)
        self.raw_provider = raw_provider
        self.base_url = _normalize_base_url(settings.AI_BASE_URL or "", self.provider)
        self.api_key = (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY") or "").strip()
        self.model = (settings.AI_MODEL or "").strip()
        self.fallback_models = [
            model.strip()
            for model in (settings.AI_MODEL_FALLBACKS or "").split(",")
            if model.strip()
        ]
        self.timeout = settings.AI_TIMEOUT_SECONDS or 30

    @property
    def is_configured(self) -> bool:
        return self.is_configured_for(self.model)

    def is_configured_for(self, model: str | None = None) -> bool:
        selected_model = (model or self.model or "").strip()
        if self.provider == "ollama":
            return bool(self.base_url and selected_model)
        return bool(self.provider and self.base_url and selected_model and self.api_key)

    def _with_agroai_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        enriched = [dict(message) for message in messages]
        for message in enriched:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content', '')}\n\n{AGRO_AI_OPERATING_CONTEXT}".strip()
                return enriched
        return [{"role": "system", "content": AGRO_AI_OPERATING_CONTEXT}] + enriched

    def _candidate_models(self, primary: str | None) -> list[str]:
        candidates: list[str] = []
        for model in [primary or self.model, *self.fallback_models]:
            clean = (model or "").strip()
            if clean and clean not in candidates:
                candidates.append(clean)
        return candidates

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
        model_override: str | None = None,
    ) -> AIGatewayResult:
        messages = self._with_agroai_context(messages)
        selected_model = (model_override or self.model or "").strip()
        if not self.is_configured_for(selected_model):
            return self._offline_fallback(messages, selected_model or None)

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
                        "summary": "I could not reach a live model provider for this request. The workspace evidence layer is still available, but no live model inference was completed.",
                        "answer": "I could not reach a live model provider for this request. The workspace evidence layer is still available, but no live model inference was completed.",
                        "available_data": [],
                        "missing_data": ["live model response"],
                        "agent_plan": ["Check provider credentials, model availability, and endpoint health before retrying."],
                        "recommendations": ["Retry once the model provider is reachable."],
                        "next_actions": ["check_model_provider", "retry_with_workspace_context"],
                        "customer_safe": True,
                    }
                ),
                provider=self.raw_provider or self.provider or "unconfigured",
                model=selected_model or None,
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
        if isinstance(value, str) and value.strip():
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
            joined = "\n".join(parts).strip()
            if joined:
                return joined
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        return reasoning if isinstance(reasoning, str) else ""

    async def _post_openai_payload(self, client: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = f"{self.base_url}/chat/completions"
        response = await client.post(endpoint, headers=headers, json=payload)
        if response.status_code in {400, 422} and "response_format" in payload:
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            response = await client.post(endpoint, headers=headers, json=retry_payload)
        response.raise_for_status()
        return response.json()

    def _should_try_next_model(self, exc: httpx.HTTPStatusError) -> bool:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code in {401, 403}:
            return False
        return status_code in {400, 404, 408, 409, 422, 429, 500, 502, 503, 504}

    async def _chat_openai_compatible(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, Any] | None,
        model_override: str | None = None,
    ) -> AIGatewayResult:
        headers = self._headers()
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for candidate_model in self._candidate_models(model_override):
                payload: dict[str, Any] = {
                    "model": candidate_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 4500,
                }
                if response_format:
                    payload["response_format"] = response_format

                try:
                    body = await self._post_openai_payload(client, headers, payload)
                except httpx.HTTPStatusError as exc:
                    response_text = ""
                    try:
                        response_text = exc.response.text[:500]
                    except Exception:
                        response_text = ""
                    errors.append(f"{candidate_model}: HTTP {exc.response.status_code if exc.response else 'unknown'} {response_text}")
                    if not self._should_try_next_model(exc):
                        raise
                    continue

                raw_content = self._message_content(body)
                content = extract_final_answer(raw_content)

                if not content:
                    final_payload = dict(payload)
                    final_payload["messages"] = messages + [
                        {"role": "assistant", "content": str(raw_content)[:6000]},
                        {"role": "user", "content": FINAL_ANSWER_PROMPT},
                    ]
                    final_body = await self._post_openai_payload(client, headers, final_payload)
                    final_raw = self._message_content(final_body)
                    content = extract_final_answer(final_raw)
                    body = {"first_response": body, "final_response": final_body}

                if not content:
                    content = json.dumps(
                        {
                            "summary": "The model provider responded, but did not return a customer-safe final answer. A clean retry with the same workspace context is required.",
                            "answer": "The model provider responded, but did not return a customer-safe final answer. A clean retry with the same workspace context is required.",
                            "available_data": [],
                            "missing_data": ["customer-safe final model answer"],
                            "agent_plan": ["Retry with stricter final-answer instruction."],
                            "integration_status": [],
                            "recommendations": ["Retry with the same workspace context and a stricter final-answer instruction."],
                            "next_actions": ["retry_with_grounded_context"],
                            "confidence": "low",
                            "customer_safe": True,
                        }
                    )

                raw: dict[str, Any] = body if isinstance(body, dict) else {"response": body}
                if errors:
                    raw = {"selected_model_response": body, "previous_model_errors": errors}

                return AIGatewayResult(status="ok", content=content, provider=self.raw_provider or self.provider, model=candidate_model, raw=raw)

        raise ValueError("All configured AI models failed: " + " | ".join(errors))

    async def _chat_ollama(self, messages: list[dict[str, str]], temperature: float, model_override: str | None = None) -> AIGatewayResult:
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
        return AIGatewayResult(status="ok", content=content, provider="ollama", model=model_override or self.model, raw=body)

    def _offline_fallback(self, messages: list[dict[str, str]], selected_model: str | None = None) -> AIGatewayResult:
        user_message = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        missing = []
        if not self.provider:
            missing.append("AI_PROVIDER")
        if not self.base_url:
            missing.append("AI_BASE_URL")
        if self.provider != "ollama" and not self.api_key:
            missing.append("AI_API_KEY or OPENROUTER_API_KEY")
        if not selected_model:
            missing.append("AI_MODEL or model override")
        content = json.dumps(
            {
                "status": "unavailable",
                "summary": "I can see the request, but live inference is not available. I should not pretend to analyze the workspace with a model until the provider is reachable.",
                "answer": "I can see the request, but live inference is not available. I should not pretend to analyze the workspace with a model until the provider is reachable.",
                "request_received": user_message[:500],
                "missing_data": missing or ["live model provider"],
                "risk_flags": ["No live model inference was performed."],
                "agent_plan": ["Configure the hosted model provider, then rerun the request against tenant-scoped workspace context."],
                "recommendations": ["Keep this in safe mode until the hosted model endpoint is reachable."],
                "next_actions": ["configure_model_provider", "retry_with_workspace_context"],
                "customer_safe": True,
            }
        )
        return AIGatewayResult(status="unavailable", content=content, provider=self.raw_provider or self.provider or "offline", model=selected_model, demo_fallback=True)


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
        "chain of thought",
        "scratchpad",
        "hidden reasoning",
        "let me think step by step",
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
            "answer": "",
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
            "answer": text,
            "available_data": [],
            "missing_data": ["structured model JSON"],
            "recommended_next_actions": ["review current evidence context", "retry request"],
            "confidence": "low",
            "customer_safe": True,
        }
    if isinstance(value, dict):
        return value
    return {
        "summary": str(value),
        "answer": str(value),
        "available_data": [],
        "missing_data": ["structured model JSON object"],
        "recommended_next_actions": ["review current evidence context", "retry request"],
        "confidence": "low",
        "customer_safe": True,
    }

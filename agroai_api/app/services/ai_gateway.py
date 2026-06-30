"""Provider-agnostic AI gateway for AGRO-AI model endpoints."""
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
Always preserve provenance: measured, reported, estimated, inferred, sample, and missing are different.
Sound natural, calm, direct, and specific. Do not invent live integrations, telemetry, yields, compliance status, savings, or customer facts.
Return valid JSON only. Put the natural answer in summary and answer.
"""

LOCAL_OLLAMA_SYSTEM_PROMPT = """
/no_think
You are AGRO-AI, an agriculture operations assistant.
Answer the user in normal customer-facing text, not JSON.
Be brief, natural, and specific. Maximum 90 words.
If data is missing, say what is missing and what the user can do next.
Do not invent telemetry, acreage, integrations, water use, compliance status, or savings.
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
    for suffix in ("/chat/completions", "/completions"):
        while base_url.lower().endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
    if not base_url and provider == "openai_compatible" and (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY")):
        base_url = "https://openrouter.ai/api/v1"
    return base_url


def _strip_markdown_fences(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        return "\n".join(lines).strip()
    return text


def clean_model_text(content: str) -> str:
    """Clean model text into customer-facing text.

    Local small Qwen models can leak JSON-ish envelopes or thinking traces. This
    function extracts only the natural answer/summary before the UI sees it.
    """

    text = (content or "").strip()
    if not text:
        return ""

    lower = text.lower()
    if "</think>" in lower:
        text = text[lower.rfind("</think>") + len("</think>") :].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = _strip_markdown_fences(text)

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            for key in ("answer", "summary", "message", "content"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
    except json.JSONDecodeError:
        pass

    for key in ("answer", "summary"):
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)', text, flags=re.DOTALL)
        if match:
            rescued = match.group(1)
            try:
                rescued = json.loads(f'"{rescued}"')
            except json.JSONDecodeError:
                rescued = rescued.replace('\\n', '\n').replace('\\"', '"')
            return str(rescued).strip()

    if text.lstrip().startswith("{"):
        return "I can help with that. I have limited live workspace evidence right now, so the useful next step is to connect or upload the relevant field, irrigation, weather, controller, or compliance data, then ask one specific question."

    return text.strip()


# Backward-compatible names used by other services.
def extract_final_answer(content: str) -> str:
    return clean_model_text(content)


def sanitize_model_text(content: str) -> str:
    return clean_model_text(content)


def parse_model_json(content: str) -> dict[str, Any]:
    text = clean_model_text(content)
    if not text:
        return {
            "summary": "",
            "answer": "",
            "available_data": [],
            "missing_data": [],
            "recommended_next_actions": [],
            "confidence": "low",
            "customer_safe": True,
            "_safe_mode": True,
        }

    try:
        value = json.loads((content or "").strip())
        if isinstance(value, dict):
            if not value.get("summary") and value.get("answer"):
                value["summary"] = value["answer"]
            if not value.get("answer") and value.get("summary"):
                value["answer"] = value["summary"]
            return value
    except json.JSONDecodeError:
        pass

    return {
        "summary": text,
        "answer": text,
        "available_data": [],
        "missing_data": [],
        "recommended_next_actions": [],
        "confidence": "low",
        "customer_safe": True,
    }


class AIGateway:
    """Thin gateway for OpenAI-compatible chat completions and Ollama."""

    def __init__(self) -> None:
        raw_provider = (settings.AI_PROVIDER or "").strip().lower()
        self.provider = _normalize_provider(raw_provider)
        self.raw_provider = raw_provider
        self.base_url = _normalize_base_url(settings.AI_BASE_URL or "", self.provider)
        self.api_key = (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY") or "").strip()
        self.model = (settings.AI_MODEL or "").strip()
        self.fallback_models = [m.strip() for m in (settings.AI_MODEL_FALLBACKS or "").split(",") if m.strip()]
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
        if self.provider == "ollama":
            return self._local_ollama_messages(messages)
        enriched = [dict(message) for message in messages]
        for message in enriched:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content', '')}\n\n{AGRO_AI_OPERATING_CONTEXT}".strip()
                return enriched
        return [{"role": "system", "content": AGRO_AI_OPERATING_CONTEXT}] + enriched

    def _local_ollama_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        user_parts: list[str] = []
        for message in messages[-3:]:
            role = message.get("role") or "user"
            content = str(message.get("content") or "").strip()
            if content:
                user_parts.append(f"{role}: {content[:900]}")
        compact = "\n\n".join(user_parts)[-2200:]
        return [
            {"role": "system", "content": LOCAL_OLLAMA_SYSTEM_PROMPT},
            {"role": "user", "content": f"/no_think\n{compact}\n\nAnswer in normal text only. No JSON."},
        ]

    def _candidate_models(self, primary: str | None) -> list[str]:
        candidates: list[str] = []
        for model in [primary or self.model, *self.fallback_models]:
            clean = (model or "").strip()
            if clean and not (self.provider == "ollama" and "/" in clean):
                if clean not in candidates:
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
                return await self._chat_ollama(messages, temperature, model_override=model_override)
            return await self._chat_openai_compatible(messages, temperature, response_format, model_override=model_override)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return AIGatewayResult(
                status="unavailable",
                content=json.dumps({
                    "summary": "I could not reach a live model provider for this request.",
                    "answer": "I could not reach a live model provider for this request.",
                    "missing_data": ["live model response"],
                    "next_actions": ["check_model_provider", "retry_with_workspace_context"],
                    "customer_safe": True,
                }),
                provider=self.raw_provider or self.provider or "unconfigured",
                model=selected_model or None,
                demo_fallback=True,
                error=str(exc),
            )

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
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
                elif isinstance(item, dict) and isinstance(item.get("text") or item.get("content"), str):
                    parts.append(item.get("text") or item.get("content"))
            return "\n".join(parts).strip()
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
        return status_code in {400, 402, 404, 408, 409, 422, 429, 500, 502, 503, 504}

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
                    response_text = exc.response.text[:500] if exc.response is not None else ""
                    errors.append(f"{candidate_model}: HTTP {exc.response.status_code if exc.response else 'unknown'} {response_text}")
                    if not self._should_try_next_model(exc):
                        raise
                    continue

                raw_content = self._message_content(body)
                content = clean_model_text(raw_content)
                if response_format:
                    try:
                        json.loads(raw_content)
                        content = raw_content
                    except json.JSONDecodeError:
                        content = json.dumps({"summary": content, "answer": content, "customer_safe": True})
                raw: dict[str, Any] = body if isinstance(body, dict) else {"response": body}
                if errors:
                    raw = {"selected_model_response": body, "previous_model_errors": errors}
                return AIGatewayResult(status="ok", content=content, provider=self.raw_provider or self.provider, model=candidate_model, raw=raw)
        raise ValueError("All configured AI models failed: " + " | ".join(errors))

    async def _chat_ollama(self, messages: list[dict[str, str]], temperature: float, model_override: str | None = None) -> AIGatewayResult:
        selected_model = model_override or self.model
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": min(float(temperature or 0.15), 0.25),
                "num_predict": 120,
                "num_ctx": 1024,
            },
        }
        async with httpx.AsyncClient(timeout=min(self.timeout, 45)) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        content = clean_model_text(body.get("message", {}).get("content", ""))
        if not content:
            content = "I can help. Ask one specific irrigation, field, compliance, or evidence question, and I will work from the connected data without inventing missing facts."
        return AIGatewayResult(status="ok", content=content, provider="ollama", model=selected_model, raw=body)

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
        content = json.dumps({
            "summary": "I can see the request, but live inference is not available.",
            "answer": "I can see the request, but live inference is not available.",
            "request_received": user_message[:500],
            "missing_data": missing or ["live model provider"],
            "next_actions": ["configure_model_provider", "retry_with_workspace_context"],
            "customer_safe": True,
        })
        return AIGatewayResult(status="unavailable", content=content, provider=self.raw_provider or self.provider or "offline", model=selected_model, demo_fallback=True)

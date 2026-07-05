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
{"summary":"...","answer":"...","work_completed":[],"available_data":[],"missing_data":[],"agent_plan":[],"integration_status":[],"recommendations":[],"next_actions":[],"risk_flags":[],"confidence":"low|medium|high","customer_safe":true}
"""

AGRO_AI_OPERATING_CONTEXT = """
You are AGRO-AI's live operating intelligence layer, not a generic chatbot.
AGRO-AI turns fragmented agriculture data into decisions, evidence records, alerts, and enterprise reporting.
The first wedge is irrigation, water-use, compliance, and field operations. The broader product direction is Terris: a field intelligence layer and operating evidence graph for agriculture.
Always preserve provenance: measured, reported, estimated, inferred, sample, and missing are different.
Sound natural, calm, direct, and specific. Do not invent live integrations, telemetry, yields, compliance status, savings, or customer facts.
"""

LOCAL_OLLAMA_SYSTEM_PROMPT = """
/no_think
You are AGRO-AI, a serious agriculture operations intelligence operator.
Answer the user's exact request directly in normal customer-facing text.
Use recent chat history, uploaded file summaries, workspace context, and available evidence when relevant.
Adapt depth to the request. Do not repeat a prior answer unless asked.
Do not output backend labels, debug text, <think> tags, or fabricated facts.
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
    if provider in {"openrouter", "openrouter.ai"}:
        return "openrouter"
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        return "openai_compatible"
    return provider


def _normalize_base_url(value: str, provider: str) -> str:
    base_url = (value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        while base_url.lower().endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
    if not base_url and provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    return base_url


def _strip_markdown_fences(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        return "\n".join(line for line in text.splitlines() if not line.strip().startswith("```")).strip()
    return text


def clean_model_text(content: str) -> str:
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
    if text.lstrip().startswith("{"):
        return ""
    return text.strip()


def extract_final_answer(content: str) -> str:
    return clean_model_text(content)


def sanitize_model_text(content: str) -> str:
    return clean_model_text(content)


def parse_model_json(content: str) -> dict[str, Any]:
    raw = (content or "").strip()
    if not raw:
        return {"summary":"","answer":"","available_data":[],"missing_data":[],"recommended_next_actions":[],"confidence":"low","customer_safe":True,"_safe_mode":True,"error":"live_model_unavailable"}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            if not value.get("summary") and value.get("answer"):
                value["summary"] = value["answer"]
            if not value.get("answer") and value.get("summary"):
                value["answer"] = value["summary"]
            return value
    except json.JSONDecodeError:
        pass
    text = clean_model_text(raw)
    if not text:
        return {"summary":"","answer":"","available_data":[],"missing_data":[],"recommended_next_actions":[],"confidence":"low","customer_safe":True,"_safe_mode":True,"error":"live_model_unavailable"}
    return {"summary":text,"answer":text,"available_data":[],"missing_data":[],"recommended_next_actions":[],"confidence":"low","customer_safe":True}


def _extract_question(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        for pattern in (r"Exact current question:\s*(.+?)(?:\n|$)", r"Exact user question:\s*(.+?)(?:\n|$)", r"QUESTION:\s*(.+?)(?:\n|$)", r"Question:\s*(.+?)(?:\n|$)"):
            match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()[:1600]
        if content.strip():
            return content.strip()[:1600]
    return ""


class AIGateway:
    def __init__(self) -> None:
        raw_provider = (settings.AI_PROVIDER or "").strip().lower()
        self.provider = _normalize_provider(raw_provider)
        self.raw_provider = raw_provider
        self.base_url = _normalize_base_url(settings.AI_BASE_URL or "", self.provider)
        if self.provider == "openrouter":
            self.api_key = (settings.AI_API_KEY or os.getenv("OPENROUTER_API_KEY") or "").strip()
        elif self.provider == "openai_compatible":
            self.api_key = (settings.AI_API_KEY or "").strip()
        else:
            self.api_key = ""
        self.model = (settings.AI_MODEL or "").strip()
        self.fallback_models = [m.strip() for m in (settings.AI_MODEL_FALLBACKS or "").split(",") if m.strip()]
        self.timeout = settings.AI_TIMEOUT_SECONDS or 30

    @property
    def is_configured(self) -> bool:
        return self.is_configured_for(self.model)

    def is_configured_for(self, model: str | None = None) -> bool:
        selected = (model or self.model or "").strip()
        if self.provider == "ollama":
            return bool(self.base_url and selected and "/" not in selected)
        if self.provider in {"openrouter", "openai_compatible"}:
            return bool(self.base_url and selected and self.api_key)
        return False

    def _with_agroai_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        if self.provider == "ollama":
            return self._local_ollama_messages(messages)
        enriched = [dict(message) for message in messages]
        for message in enriched:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content', '')}\n\n{AGRO_AI_OPERATING_CONTEXT}".strip()
                return enriched
        return [{"role":"system","content":AGRO_AI_OPERATING_CONTEXT}] + enriched

    def _local_ollama_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        question = _extract_question(messages)
        parts: list[str] = []
        for message in messages[-10:]:
            role = message.get("role") or "user"
            content = str(message.get("content") or "").strip()
            if content:
                parts.append(f"{role}: {content[:2200]}")
        compact = "\n\n".join(parts)[-12000:]
        return [{"role":"system","content":LOCAL_OLLAMA_SYSTEM_PROMPT},{"role":"user","content":f"/no_think\nQUESTION: {question}\n\nWorkspace, uploaded evidence, and recent context:\n{compact}\n\nAnswer the QUESTION directly. Cater to the user's wording, depth, and desired output."}]

    def _candidate_models(self, primary: str | None, max_model_attempts: int | None = None) -> list[str]:
        out: list[str] = []
        for model in [primary or self.model, *self.fallback_models]:
            value = (model or "").strip()
            if value and not (self.provider == "ollama" and "/" in value) and value not in out:
                out.append(value)
        return out[:max_model_attempts] if max_model_attempts and max_model_attempts > 0 else out

    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2, response_format: dict[str, Any] | None = None, model_override: str | None = None, max_tokens: int | None = None, timeout_seconds: int | None = None, max_model_attempts: int | None = None) -> AIGatewayResult:
        selected = (model_override or self.model or "").strip()
        if not self.is_configured_for(selected):
            return self._offline_fallback(selected or None)
        enriched = self._with_agroai_context(messages)
        try:
            if self.provider == "ollama":
                return await self._chat_ollama(enriched, temperature, model_override=model_override, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
            if model_override or max_tokens or timeout_seconds or max_model_attempts:
                return await self._chat_openai_compatible(enriched, temperature, response_format, model_override=model_override, max_tokens=max_tokens, timeout_seconds=timeout_seconds, max_model_attempts=max_model_attempts)
            return await self._chat_openai_compatible(enriched, temperature, response_format)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return AIGatewayResult(status="unavailable", content="", provider=self.raw_provider or self.provider or "unconfigured", model=selected or None, error=str(exc))

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"}
        if self.provider == "openrouter" or "openrouter.ai" in self.base_url.lower():
            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"
        return headers

    @staticmethod
    def _message_content(body: dict[str, Any]) -> str:
        message = body["choices"][0].get("message") or {}
        value = message.get("content")
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(str(item.get("text") or item.get("content") or item) if isinstance(item, dict) else str(item) for item in value).strip()
        return ""

    async def _post_openai_payload(self, client: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        if response.status_code in {400, 422} and "response_format" in payload:
            retry = dict(payload)
            retry.pop("response_format", None)
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=retry)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _should_try_next_model(exc: httpx.HTTPStatusError) -> bool:
        code = exc.response.status_code if exc.response is not None else 0
        return False if code in {401,403} else code in {400,402,404,408,409,422,429,500,502,503,504}

    async def _chat_openai_compatible(self, messages: list[dict[str, str]], temperature: float, response_format: dict[str, Any] | None, model_override: str | None = None, max_tokens: int | None = None, timeout_seconds: int | None = None, max_model_attempts: int | None = None) -> AIGatewayResult:
        errors: list[str] = []
        candidates = self._candidate_models(model_override, max_model_attempts)
        if not candidates:
            return AIGatewayResult(status="unavailable", content="", provider=self.raw_provider or self.provider, model=None, error="No compatible model candidates configured.")
        async with httpx.AsyncClient(timeout=max(4, min(int(timeout_seconds or self.timeout or 18), 75))) as client:
            for model in candidates:
                payload: dict[str, Any] = {"model":model,"messages":messages,"temperature":temperature,"max_tokens":int(max_tokens or 1200)}
                if response_format:
                    payload["response_format"] = response_format
                try:
                    body = await self._post_openai_payload(client, self._headers(), payload)
                except httpx.HTTPStatusError as exc:
                    errors.append(f"{model}: HTTP {exc.response.status_code if exc.response else 'unknown'}")
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
                        content = json.dumps({"summary":content,"answer":content,"customer_safe":True})
                if not content:
                    errors.append(f"{model}: empty_content")
                    continue
                return AIGatewayResult(status="ok", content=content, provider=self.raw_provider or self.provider, model=model, raw=body)
        return AIGatewayResult(status="unavailable", content="", provider=self.raw_provider or self.provider, model=None, error="All configured AI models failed: " + " | ".join(errors))

    async def _chat_ollama(self, messages: list[dict[str, str]], temperature: float, model_override: str | None = None, max_tokens: int | None = None, timeout_seconds: int | None = None) -> AIGatewayResult:
        selected = (model_override or self.model or "").strip()
        if not selected or "/" in selected:
            return AIGatewayResult(status="unavailable", content="", provider="ollama", model=selected or None, error="No compatible local Ollama model configured.")
        question = _extract_question(messages)
        deep = any(term in question.lower() for term in ("report","analysis","pdf","document","packet","plan","diagnose","detailed","explain"))
        payload = {"model":selected,"messages":messages,"stream":False,"think":False,"keep_alive":"45m","options":{"temperature":min(float(temperature or 0.18),0.35),"num_predict":max(200,min(int(max_tokens or (1800 if deep else 1200)),2800)),"num_ctx":8192 if deep else 6144,"top_p":0.9}}
        async with httpx.AsyncClient(timeout=max(12,min(int(timeout_seconds or (75 if deep else 35)),90))) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        content = clean_model_text(((body.get("message") or {}).get("content") or body.get("response") or "") if isinstance(body, dict) else "")
        if not content:
            return AIGatewayResult(status="unavailable", content="", provider="ollama", model=selected, raw=body if isinstance(body, dict) else {"response":body}, error="Ollama returned no usable content.")
        return AIGatewayResult(status="ok", content=content, provider="ollama", model=selected, raw=body)

    def _offline_fallback(self, selected_model: str | None = None) -> AIGatewayResult:
        return AIGatewayResult(
            status="unavailable",
            content=(
                "AI unavailable/demo fallback: no live model provider is configured. "
                "AGRO-AI can only return deterministic safe-mode guidance until AI_PROVIDER, AI_BASE_URL, and AI_MODEL are set."
            ),
            provider=self.raw_provider or self.provider or "offline",
            model=selected_model,
            demo_fallback=True,
            error="Live model provider is not configured for this request.",
        )

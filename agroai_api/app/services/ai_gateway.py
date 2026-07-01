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
You are AGRO-AI, a serious agriculture operations intelligence assistant.
Answer the user's exact question in normal customer-facing text, not JSON.
Do not sound like a status bot. Do not repeat generic onboarding copy.
Use the workspace context, imported file summaries, and recent chat history.
Be useful: explain what you found, what it means, and what the operator should do next.
When the user asks for a report, analysis, checklist, decision, or plan, produce a structured answer with clear sections.
When data is missing, continue with a useful draft and clearly label what still needs verification.
Never invent live telemetry, acreage, integrations, water use, compliance status, savings, or customer facts.
Target length: 180-350 words unless the user asks for something shorter.
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
        return ""

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


def _extract_question(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        for pattern in [r"QUESTION:\s*(.+?)(?:\n|$)", r"Question:\s*(.+?)(?:\n|$)", r'"question"\s*:\s*"((?:[^"\\]|\\.)*)"']:
            match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                try:
                    value = json.loads(f'"{value}"')
                except Exception:
                    value = value.replace('\\n', ' ').replace('\\"', '"')
                return str(value).strip()[:700]
        if content.strip():
            return content.strip()[:700]
    return ""


def _question_aware_local_fallback(question: str) -> str:
    q = (question or "").lower()
    if any(term in q for term in ["john deere", "deere", "operations center"]):
        return "Yes. John Deere Operations Center is one of the systems AGRO-AI should connect to because it can carry field boundaries, machine activity, work records, and operational context. In a real customer workflow, I would use that data as one evidence source, then combine it with irrigation, ET/weather, flow, soil moisture, and compliance records before producing field priorities or customer-ready reports."
    if any(term in q for term in ["how much water", "water should", "irrigat", "put here"]):
        return "I can help, but I should not guess an irrigation amount without the field, crop, acreage, soil type, recent irrigation, ET/weather, soil moisture, flow rate, and controller status. The useful next step is to upload or connect those records. Once they are present, I can calculate a defensible recommendation, explain the evidence behind it, and flag whether the recommendation is safe, uncertain, or blocked."
    if any(term in q for term in ["what are you good", "what can you do", "capabilities", "good at"]):
        return "I am best at turning messy agriculture context into decisions: reading uploaded files, finding evidence gaps, drafting compliance reports, building field-priority lists, preparing operator checklists, reviewing irrigation and water-accounting data, and translating raw records into customer-ready actions. My value should not be vague chat; it should be helping a farm, district, advisor, or lender decide what needs attention, what evidence supports it, and what to do next."
    if any(term in q for term in ["hi", "hello", "hey"]):
        return "Yes — I can help. Give me a field, file, report, irrigation question, compliance requirement, or customer account. I will separate what is known, what is missing, what can be done now, and what should become an operator action."
    return "I can help with that. I would start by separating the available evidence from the assumptions, then turn the request into one of four outputs: an operator action list, an evidence gap review, a field or irrigation decision, or a customer-ready report draft."


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
        question = _extract_question(messages)
        context_parts: list[str] = []
        for message in messages[-5:]:
            role = message.get("role") or "user"
            content = str(message.get("content") or "").strip()
            if content:
                context_parts.append(f"{role}: {content[:1100]}")
        compact = "\n\n".join(context_parts)[-3600:]
        return [
            {"role": "system", "content": LOCAL_OLLAMA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"/no_think\nQUESTION: {question}\n\n"
                    f"Workspace and recent context:\n{compact}\n\n"
                    "Answer the QUESTION directly. Be specific, useful, and action-oriented. No JSON. No backend labels."
                ),
            },
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
        question = _extract_question(messages)
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "45m",
            "options": {
                "temperature": min(float(temperature or 0.18), 0.35),
                "num_predict": 360,
                "num_ctx": 2048,
                "top_p": 0.9,
            },
        }
        async with httpx.AsyncClient(timeout=max(min(self.timeout, 75), 45)) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
        message = body.get("message", {}) if isinstance(body, dict) else {}
        content = clean_model_text(message.get("content", "") or body.get("response", ""))
        if not content:
            content = _question_aware_local_fallback(question)
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

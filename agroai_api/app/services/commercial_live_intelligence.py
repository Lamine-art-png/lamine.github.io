"""Commercially budgeted wrapper around the hardened LiveIntelligence runtime.

The existing runtime keeps provider selection, language repair, invariants, and
no-fake-output behavior. This subclass only bounds compute according to the resolved
commercial intelligence policy.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.services.intelligence_policy import IntelligencePolicy
from app.services.live_intelligence import LiveIntelligence, LiveResult


class CommercialLiveIntelligence(LiveIntelligence):
    def __init__(self, policy: IntelligencePolicy) -> None:
        super().__init__()
        self.policy = policy

    @staticmethod
    def _bounded_messages(messages: list[dict[str, str]], max_chars: int) -> list[dict[str, str]]:
        system = next((dict(item) for item in messages if item.get("role") == "system"), None)
        remaining = max(0, max_chars - len(str((system or {}).get("content") or "")))
        output: list[dict[str, str]] = []
        for item in reversed([row for row in messages if row.get("role") != "system"]):
            if remaining <= 0:
                break
            content = str(item.get("content") or "")
            kept = content[-remaining:]
            output.append({**item, "content": kept})
            remaining -= len(kept)
        output.reverse()
        return ([system] if system else []) + output

    async def run_remote(
        self,
        cfg: tuple[str, str, str],
        models: list[str],
        messages: list[dict[str, str]],
        profile: str,
    ) -> tuple[str, str] | None:
        endpoint, key, provider = cfg
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            from app.core.config import settings

            headers["HTTP-Referer"] = settings.APP_URL or "https://app.agroai-pilot.com"
            headers["X-Title"] = "AGRO-AI Enterprise Portal"

        bounded = self._bounded_messages(messages, self.policy.max_context_chars)
        timeout = max(8, min(int(self.policy.timeout_seconds), 90))
        attempts = max(1, int(self.policy.max_model_attempts))
        max_tokens = max(400, int(self.policy.max_output_tokens))

        async with httpx.AsyncClient(timeout=timeout) as client:
            for model in models[:attempts]:
                try:
                    response = await client.post(
                        f"{endpoint}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": bounded,
                            "temperature": 0.2,
                            "max_tokens": max_tokens,
                        },
                    )
                    if response.status_code in {401, 403}:
                        return None
                    if response.status_code >= 400:
                        continue
                    answer = self.content(response.json())
                    if answer:
                        return answer, model
                except (httpx.HTTPError, ValueError, KeyError):
                    continue
        return None

    async def run_local(
        self,
        model: str,
        messages: list[dict[str, str]],
        profile: str,
    ) -> tuple[str, str] | None:
        bounded = self._bounded_messages(messages, self.policy.max_context_chars)
        num_ctx = 16384 if self.policy.max_context_chars > 32000 else 8192 if self.policy.max_context_chars > 12000 else 4096
        payload: dict[str, Any] = {
            "model": model,
            "messages": bounded,
            "stream": False,
            "think": False,
            "keep_alive": "45m",
            "options": {
                "temperature": 0.2,
                "num_predict": max(400, int(self.policy.max_output_tokens)),
                "num_ctx": num_ctx,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=max(20, min(int(self.policy.timeout_seconds), 90))) as client:
                response = await client.post(f"{self.base}/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
            answer = str((body.get("message") or {}).get("content") or body.get("response") or "").strip()
            return (answer, model) if answer else None
        except (httpx.HTTPError, ValueError, KeyError):
            return None

    async def run(
        self,
        task: str,
        question: str,
        messages: list[dict[str, str]],
        preferred_language: str | None,
    ) -> LiveResult:
        bounded = self._bounded_messages(messages, self.policy.max_context_chars)
        return await super().run(task, question, bounded, preferred_language)

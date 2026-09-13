from __future__ import annotations

import uuid
from typing import Any

from .client import AgroAIPlatformClient, AsyncAgroAIPlatformClient


class AgroAI(AgroAIPlatformClient):
    """Simple AGRO-AI client centered on agricultural intelligence runs.

    Example:
        client = AgroAI()
        run = client.intelligence(
            task="field_diagnosis",
            question="What needs attention today?",
            input={"crop": "tomato", "location": "Fresno, CA"},
        )
    """

    def intelligence(
        self,
        *,
        question: str,
        task: str = "general",
        input: dict[str, Any] | None = None,
        field_id: str | None = None,
        audience: str | None = None,
        language: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "question": question,
            "input": input or {},
        }
        if field_id:
            payload["field_id"] = field_id
        if audience:
            payload["audience"] = audience
        if language:
            payload["language"] = language
        return self.request(
            "POST",
            "/v1/platform/intelligence",
            json=payload,
            idempotency_key=idempotency_key or f"intel_{uuid.uuid4().hex}",
        ).data

    def get_intelligence_run(self, run_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/platform/intelligence/{run_id}").data


class AsyncAgroAI(AsyncAgroAIPlatformClient):
    async def intelligence(
        self,
        *,
        question: str,
        task: str = "general",
        input: dict[str, Any] | None = None,
        field_id: str | None = None,
        audience: str | None = None,
        language: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "question": question,
            "input": input or {},
        }
        if field_id:
            payload["field_id"] = field_id
        if audience:
            payload["audience"] = audience
        if language:
            payload["language"] = language
        return (
            await self.request(
                "POST",
                "/v1/platform/intelligence",
                json=payload,
                idempotency_key=idempotency_key or f"intel_{uuid.uuid4().hex}",
            )
        ).data

    async def get_intelligence_run(self, run_id: str) -> dict[str, Any]:
        return (await self.request("GET", f"/v1/platform/intelligence/{run_id}")).data

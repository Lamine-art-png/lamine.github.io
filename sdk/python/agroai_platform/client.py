from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterator

import requests


@dataclass(frozen=True)
class RateLimitMetadata:
    limit: int | None
    remaining: int | None
    reset: int | None
    retry_after: int | None


class AgroAIPlatformError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


class AgroAIPlatformClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("AGROAI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AGROAI_BASE_URL", "https://api.agroai-pilot.com")).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("AGROAI_API_KEY is required")

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "X-Request-Id": f"req_{uuid.uuid4().hex}",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(self, method: str, path: str, *, json: Any | None = None, idempotency_key: str | None = None, retry_idempotent_reads: bool = True) -> tuple[dict[str, Any], RateLimitMetadata]:
        attempts = 2 if method.upper() in {"GET", "HEAD"} and retry_idempotent_reads else 1
        last_response = None
        for attempt in range(attempts):
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=self._headers(idempotency_key=idempotency_key),
                timeout=self.timeout,
            )
            last_response = response
            if response.status_code < 500 or attempt + 1 >= attempts:
                break
            time.sleep(0.25)
        assert last_response is not None
        metadata = RateLimitMetadata(
            limit=_int_header(last_response, "RateLimit-Limit"),
            remaining=_int_header(last_response, "RateLimit-Remaining"),
            reset=_int_header(last_response, "RateLimit-Reset"),
            retry_after=_int_header(last_response, "Retry-After"),
        )
        payload = last_response.json() if last_response.content else {}
        if not last_response.ok:
            raise AgroAIPlatformError(
                payload.get("message") or payload.get("detail", {}).get("message") or "AGRO-AI Platform API request failed",
                status_code=last_response.status_code,
                code=payload.get("code") or payload.get("detail", {}).get("code"),
                request_id=payload.get("request_id") or payload.get("detail", {}).get("request_id"),
            )
        return payload, metadata

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/v1/platform/me")[0]

    def providers(self) -> dict[str, Any]:
        return self._request("GET", "/v1/platform/providers")[0]

    def plan_action(self, action_type: str, *, resource_id: str | None = None, parameters: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/platform/actions/plan",
            json={"action_type": action_type, "resource_id": resource_id, "parameters": parameters or {}},
            idempotency_key=idempotency_key or f"idem_{uuid.uuid4().hex}",
            retry_idempotent_reads=False,
        )[0]


def _int_header(response: requests.Response, name: str) -> int | None:
    value = response.headers.get(name)
    return int(value) if value and value.isdigit() else None

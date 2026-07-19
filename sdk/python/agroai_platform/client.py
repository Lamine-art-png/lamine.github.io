from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator

import httpx
import requests


@dataclass(frozen=True)
class RateLimitMetadata:
    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None
    retry_after: int | None = None


@dataclass(frozen=True)
class ApiResponse:
    data: dict[str, Any]
    request_id: str | None
    rate_limit: RateLimitMetadata


class AgroAIPlatformError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


def _error(payload: dict[str, Any], status_code: int) -> AgroAIPlatformError:
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
    return AgroAIPlatformError(
        str(detail.get("message") or "AGRO-AI Platform API request failed"),
        status_code=status_code,
        code=detail.get("code"),
        request_id=detail.get("request_id"),
    )


def _number(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _metadata(headers: Any) -> RateLimitMetadata:
    return RateLimitMetadata(
        limit=_number(headers.get("RateLimit-Limit")),
        remaining=_number(headers.get("RateLimit-Remaining")),
        reset=_number(headers.get("RateLimit-Reset")),
        retry_after=_number(headers.get("Retry-After")),
    )


class AgroAIPlatformClient:
    """Server-side synchronous client. Never embed an API key in browser code."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("AGROAI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AGROAI_BASE_URL", "https://api.agroai-pilot.com")).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("AGROAI_API_KEY is required")

    def request(self, method: str, path: str, *, json: Any | None = None, idempotency_key: str | None = None) -> ApiResponse:
        method = method.upper()
        attempts = 3 if method in {"GET", "HEAD"} else 1
        response: requests.Response | None = None
        request_id = f"req_{uuid.uuid4().hex}"
        for attempt in range(attempts):
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "X-Request-Id": request_id,
                    **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
                },
                timeout=self.timeout,
            )
            if response.status_code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                break
            time.sleep(min(2.0, 0.25 * (2**attempt)))
        assert response is not None
        payload = response.json() if response.content else {}
        if not response.ok:
            raise _error(payload, response.status_code)
        return ApiResponse(
            data=payload,
            request_id=response.headers.get("X-Request-Id") or request_id,
            rate_limit=_metadata(response.headers),
        )

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/v1/platform/me").data

    def list_fields(self, *, cursor: str | None = None, limit: int = 50) -> ApiResponse:
        query = f"?limit={min(max(limit, 1), 100)}" + (f"&cursor={cursor}" if cursor else "")
        return self.request("GET", f"/v1/platform/fields{query}")

    def iter_fields(self, *, page_size: int = 50) -> Iterator[dict[str, Any]]:
        cursor = None
        while True:
            page = self.list_fields(cursor=cursor, limit=page_size).data
            yield from page.get("items", [])
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def create_field(self, payload: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self.request("POST", "/v1/platform/fields", json=payload, idempotency_key=idempotency_key or str(uuid.uuid4())).data

    def initiate_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/platform/sources/uploads", json=payload, idempotency_key=str(uuid.uuid4())).data

    def upload_file(self, upload: dict[str, Any], content: bytes, *, content_type: str) -> None:
        url = str(upload.get("upload_url") or "")
        if not url:
            raise ValueError("upload_url is required")
        response = requests.put(url, data=content, headers={"Content-Type": content_type}, timeout=self.timeout)
        response.raise_for_status()

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/platform/jobs/{job_id}").data

    def poll_job(self, job_id: str, *, timeout: float = 120.0, interval: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.get_job(job_id)
            if result.get("job", {}).get("status") in {"succeeded", "failed", "cancelled"}:
                return result
            time.sleep(interval)
        raise TimeoutError(f"job {job_id} did not finish within {timeout} seconds")

    def usage(self) -> dict[str, Any]:
        return self.request("GET", "/v1/platform/usage").data


class AsyncAgroAIPlatformClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.getenv("AGROAI_API_KEY", "")
        self.base_url = (base_url or os.getenv("AGROAI_BASE_URL", "https://api.agroai-pilot.com")).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("AGROAI_API_KEY is required")

    async def request(self, method: str, path: str, *, json: Any | None = None, idempotency_key: str | None = None) -> ApiResponse:
        method = method.upper()
        request_id = f"req_{uuid.uuid4().hex}"
        attempts = 3 if method in {"GET", "HEAD"} else 1
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response: httpx.Response | None = None
            for attempt in range(attempts):
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                        "X-Request-Id": request_id,
                        **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
                    },
                )
                if response.status_code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                    break
                await __import__("asyncio").sleep(min(2.0, 0.25 * (2**attempt)))
        assert response is not None
        payload = response.json() if response.content else {}
        if not response.is_success:
            raise _error(payload, response.status_code)
        return ApiResponse(payload, response.headers.get("X-Request-Id") or request_id, _metadata(response.headers))

    async def iter_fields(self, *, page_size: int = 50) -> AsyncIterator[dict[str, Any]]:
        cursor = None
        while True:
            query = f"?limit={min(max(page_size, 1), 100)}" + (f"&cursor={cursor}" if cursor else "")
            page = (await self.request("GET", f"/v1/platform/fields{query}")).data
            for item in page.get("items", []):
                yield item
            cursor = page.get("next_cursor")
            if not cursor:
                return

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return (await self.request("GET", f"/v1/platform/jobs/{job_id}")).data

    async def usage(self) -> dict[str, Any]:
        return (await self.request("GET", "/v1/platform/usage")).data


def verify_webhook_signature(
    *,
    secret: str,
    body: bytes,
    timestamp: str,
    signature: str,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> bool:
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now or int(time.time())) - sent_at) > tolerance_seconds:
        return False
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    candidate = signature.removeprefix("v1=")
    return hmac.compare_digest(expected, candidate)

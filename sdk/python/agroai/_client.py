from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from typing import Any, AsyncIterator, BinaryIO, Iterator

import httpx

from ._errors import AgroAIError, APIConnectionError, APITimeoutError, error_for

DEFAULT_BASE_URL = "https://api.agroai-pilot.com"
SDK_VERSION = "0.3.0"
_RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
_TERMINAL_JOB_STATUSES = {"completed", "degraded", "failed", "canceled", "timeout"}


class APIObject(dict):
    """A response object: a plain dict that also supports attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return _wrap(self[name])
        except KeyError as exc:
            raise AttributeError(name) from exc


def _wrap(value: Any) -> Any:
    if isinstance(value, dict) and not isinstance(value, APIObject):
        return APIObject(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


# Types AGRO-AI accepts, by extension. Text formats must be declared (the
# server cannot sniff text); binary formats are verified by content anyway.
_CONTENT_TYPES_BY_EXTENSION = {
    ".txt": "text/plain",
    ".text": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def guess_content_type(filename: str | None) -> str:
    """Content type for an upload when the caller did not supply one.

    Known extensions map to the type AGRO-AI expects; anything else is sent as
    application/octet-stream, which the server accepts only for formats it can
    verify from the bytes (images, PDF) and rejects otherwise.
    """
    suffix = os.path.splitext(str(filename or ""))[1].lower()
    return _CONTENT_TYPES_BY_EXTENSION.get(suffix, "application/octet-stream")


def _response_format(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {"type": "agroai_schema", "name": value}
    if isinstance(value, dict) and value.get("type") not in {"text", "agroai_schema", "json_schema"}:
        # A bare JSON Schema (its own "type" is e.g. "object").
        return {"type": "json_schema", "schema": value}
    return value


def _knowledge(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return {"collections": list(value)}
    if isinstance(value, str):
        return {"collections": [value]}
    return value


def _attachments(value: Any) -> list[dict[str, Any]]:
    return [{"file_id": item} if isinstance(item, str) else item for item in (value or [])]


def build_run_body(
    *,
    question: str,
    task: str = "answer",
    input: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    attachments: list[Any] | None = None,
    response_format: Any = None,
    tools: list[dict[str, Any]] | None = None,
    knowledge: Any = None,
    session_id: str | None = None,
    metadata: dict[str, str] | None = None,
    field_id: str | None = None,
    workspace_id: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"task": task, "question": question}
    optional = {
        "input": input,
        "context": context,
        "attachments": _attachments(attachments) or None,
        "response_format": _response_format(response_format),
        "tools": tools or None,
        "knowledge": _knowledge(knowledge),
        "session_id": session_id,
        "metadata": metadata or None,
        "field_id": field_id,
        "workspace_id": workspace_id,
        "language": language,
    }
    body.update({key: value for key, value in optional.items() if value is not None})
    return body


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 30.0)
    return min(8.0, 0.5 * (2 ** attempt)) * (0.75 + random.random() / 2)


def _should_retry(response: httpx.Response) -> bool:
    if response.status_code == 409:
        # Only "still running" conflicts are worth retrying; a changed request is not.
        try:
            code = (response.json().get("detail") or {}).get("code")
        except Exception:  # noqa: BLE001
            return False
        return code == "intelligence_run_in_progress"
    return response.status_code in _RETRY_STATUSES


def _parse(response: httpx.Response) -> APIObject | None:
    request_id = response.headers.get("X-Request-Id")
    if response.status_code == 204 or not response.content:
        if response.is_success:
            return None
        raise error_for(response.status_code, {}, request_id)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgroAIError(f"Invalid JSON from AGRO-AI ({response.status_code})", status_code=response.status_code, request_id=request_id) from exc
    if not response.is_success:
        raise error_for(response.status_code, payload, request_id)
    return _wrap(payload)


class _SSEParser:
    def __init__(self) -> None:
        self.event, self.data = "message", []

    def feed(self, line: str) -> APIObject | None:
        if line == "":
            return self.flush()
        if line.startswith(":"):
            return None
        if line.startswith("event:"):
            self.event = line[6:].strip()
        elif line.startswith("data:"):
            self.data.append(line[5:].lstrip())
        return None

    def flush(self) -> APIObject | None:
        item = None
        if self.data:
            item = APIObject({"event": self.event, "data": _wrap(json.loads("\n".join(self.data)))})
        self.event, self.data = "message", []
        return item


def _sse_events(lines: Iterator[str]) -> Iterator[APIObject]:
    parser = _SSEParser()
    for line in lines:
        item = parser.feed(line)
        if item is not None:
            yield item
    tail = parser.flush()
    if tail is not None:
        yield tail


class _Base:
    def __init__(self, api_key: str | None, base_url: str | None, timeout: float, max_retries: int) -> None:
        self.api_key = api_key or os.getenv("AGROAI_API_KEY", "")
        if not self.api_key:
            raise AgroAIError("An AGRO-AI API key is required (api_key=... or AGROAI_API_KEY).")
        self.base_url = (base_url or os.getenv("AGROAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.intelligence = Intelligence(self)

    def _headers(self, idempotency_key: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"agroai-python/{SDK_VERSION}",
            "X-Request-Id": f"sdk_{uuid.uuid4().hex}",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        headers.update(extra or {})
        return headers

    @staticmethod
    def _retryable(method: str, idempotency_key: str | None) -> bool:
        # Writes retry only with an Idempotency-Key, which the server
        # deduplicates; a retried paid request can never be charged twice.
        return method in {"GET", "DELETE"} or bool(idempotency_key)


class AgroAI(_Base):
    """Synchronous AGRO-AI client. Server-side only: never ship an API key to a browser."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 120.0,
                 max_retries: int = 2, http_client: httpx.Client | None = None) -> None:
        super().__init__(api_key, base_url, timeout, max_retries)
        self._http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgroAI":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None,
                 idempotency_key: str | None = None, files: Any = None, data: Any = None, timeout: float | None = None) -> Any:
        attempts = 1 + (self.max_retries if self._retryable(method, idempotency_key) else 0)
        for attempt in range(attempts):
            try:
                response = self._http.request(
                    method, f"{self.base_url}{path}", json=json_body, params=params, files=files, data=data,
                    headers=self._headers(idempotency_key), timeout=timeout or self.timeout,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise APITimeoutError("Request to AGRO-AI timed out") from exc
                time.sleep(_retry_delay(attempt, None))
                continue
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    raise APIConnectionError(f"Could not reach AGRO-AI: {exc.__class__.__name__}") from exc
                time.sleep(_retry_delay(attempt, None))
                continue
            if attempt > 0 and method == "DELETE" and response.status_code == 404:
                # The earlier attempt deleted it but its response was lost:
                # the requested end state holds, so the delete succeeded.
                return None
            if attempt + 1 < attempts and _should_retry(response):
                time.sleep(_retry_delay(attempt, response))
                continue
            return _parse(response)
        raise AgroAIError("unreachable")

    def _open_stream(self, path: str, body: dict[str, Any], idempotency_key: str) -> httpx.Response:
        # Establishing the stream follows the same retry policy as _request
        # (safe: the Idempotency-Key is reused); once events flow, no retry.
        attempts = 1 + self.max_retries
        for attempt in range(attempts):
            request = self._http.build_request(
                "POST", f"{self.base_url}{path}", json=body,
                headers=self._headers(idempotency_key, {"Accept": "text/event-stream"}), timeout=self.timeout,
            )
            try:
                response = self._http.send(request, stream=True)
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise APITimeoutError("Request to AGRO-AI timed out") from exc
                time.sleep(_retry_delay(attempt, None))
                continue
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    raise APIConnectionError(f"Could not reach AGRO-AI: {exc.__class__.__name__}") from exc
                time.sleep(_retry_delay(attempt, None))
                continue
            if response.is_success:
                return response
            try:
                response.read()
            finally:
                response.close()
            if attempt + 1 < attempts and _should_retry(response):
                time.sleep(_retry_delay(attempt, response))
                continue
            _parse(response)
        raise AgroAIError("unreachable")

    def _stream(self, path: str, body: dict[str, Any], idempotency_key: str) -> Iterator[APIObject]:
        response = self._open_stream(path, body, idempotency_key)
        try:
            yield from _sse_events(response.iter_lines())
        finally:
            response.close()

    def _wait(self, job_id: str, *, timeout: float, poll_interval: float) -> APIObject:
        deadline = time.monotonic() + timeout
        while True:
            job = self._request("GET", f"/v1/intelligence/jobs/{job_id}")
            if job["status"] in _TERMINAL_JOB_STATUSES:
                return job
            if time.monotonic() >= deadline:
                raise APITimeoutError(f"Job {job_id} did not finish within {timeout} seconds (status={job['status']})")
            time.sleep(poll_interval)


class AsyncAgroAI(_Base):
    """Asynchronous AGRO-AI client (asyncio)."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 120.0,
                 max_retries: int = 2, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(api_key, base_url, timeout, max_retries)
        self._http = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAgroAI":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None,
                       idempotency_key: str | None = None, files: Any = None, data: Any = None, timeout: float | None = None) -> Any:
        attempts = 1 + (self.max_retries if self._retryable(method, idempotency_key) else 0)
        for attempt in range(attempts):
            try:
                response = await self._http.request(
                    method, f"{self.base_url}{path}", json=json_body, params=params, files=files, data=data,
                    headers=self._headers(idempotency_key), timeout=timeout or self.timeout,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise APITimeoutError("Request to AGRO-AI timed out") from exc
                await asyncio.sleep(_retry_delay(attempt, None))
                continue
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    raise APIConnectionError(f"Could not reach AGRO-AI: {exc.__class__.__name__}") from exc
                await asyncio.sleep(_retry_delay(attempt, None))
                continue
            if attempt > 0 and method == "DELETE" and response.status_code == 404:
                # The earlier attempt deleted it but its response was lost:
                # the requested end state holds, so the delete succeeded.
                return None
            if attempt + 1 < attempts and _should_retry(response):
                await asyncio.sleep(_retry_delay(attempt, response))
                continue
            return _parse(response)
        raise AgroAIError("unreachable")

    async def _open_stream(self, path: str, body: dict[str, Any], idempotency_key: str) -> httpx.Response:
        # Establishing the stream follows the same retry policy as _request
        # (safe: the Idempotency-Key is reused); once events flow, no retry.
        attempts = 1 + self.max_retries
        for attempt in range(attempts):
            request = self._http.build_request(
                "POST", f"{self.base_url}{path}", json=body,
                headers=self._headers(idempotency_key, {"Accept": "text/event-stream"}), timeout=self.timeout,
            )
            try:
                response = await self._http.send(request, stream=True)
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise APITimeoutError("Request to AGRO-AI timed out") from exc
                await asyncio.sleep(_retry_delay(attempt, None))
                continue
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    raise APIConnectionError(f"Could not reach AGRO-AI: {exc.__class__.__name__}") from exc
                await asyncio.sleep(_retry_delay(attempt, None))
                continue
            if response.is_success:
                return response
            try:
                await response.aread()
            finally:
                await response.aclose()
            if attempt + 1 < attempts and _should_retry(response):
                await asyncio.sleep(_retry_delay(attempt, response))
                continue
            _parse(response)
        raise AgroAIError("unreachable")

    async def _stream(self, path: str, body: dict[str, Any], idempotency_key: str) -> AsyncIterator[APIObject]:
        response = await self._open_stream(path, body, idempotency_key)
        try:
            parser = _SSEParser()
            async for line in response.aiter_lines():
                item = parser.feed(line)
                if item is not None:
                    yield item
            tail = parser.flush()
            if tail is not None:
                yield tail
        finally:
            await response.aclose()

    async def _wait(self, job_id: str, *, timeout: float, poll_interval: float) -> APIObject:
        deadline = time.monotonic() + timeout
        while True:
            job = await self._request("GET", f"/v1/intelligence/jobs/{job_id}")
            if job["status"] in _TERMINAL_JOB_STATUSES:
                return job
            if time.monotonic() >= deadline:
                raise APITimeoutError(f"Job {job_id} did not finish within {timeout} seconds (status={job['status']})")
            await asyncio.sleep(poll_interval)


# --------------------------------------------------------------------------- #
# Resources. Each method returns the client's ``_request`` result directly, so
# the same resource serves the sync client (value) and async client (awaitable).


class Intelligence:
    def __init__(self, client: _Base) -> None:
        self._client = client
        self.jobs = Jobs(client)
        self.sessions = Sessions(client)
        self.files = Files(client)
        self.knowledge = Knowledge(client)
        self.tools = Tools(client)
        self.runs = Runs(client)

    def run(self, question: str, *, idempotency_key: str | None = None, **options: Any) -> Any:
        """Run AGRO-AI Intelligence. Auto-generates an Idempotency-Key so retries are safe."""
        body = build_run_body(question=question, **options)
        return self._client._request("POST", "/v1/intelligence", json_body=body, idempotency_key=idempotency_key or f"sdk-{uuid.uuid4().hex}")

    def stream(self, question: str, *, idempotency_key: str | None = None, **options: Any) -> Any:
        """Server-sent stage events (run.created, context.ready, ..., run.completed)."""
        body = {**build_run_body(question=question, **options), "stream": True}
        return self._client._stream("/v1/intelligence", body, idempotency_key or f"sdk-{uuid.uuid4().hex}")

    def pricing(self) -> Any:
        return self._client._request("GET", "/v1/intelligence/pricing")

    def capabilities(self) -> Any:
        return self._client._request("GET", "/v1/intelligence/capabilities")

    def usage(self, *, days: int = 30) -> Any:
        return self._client._request("GET", "/v1/intelligence/usage", params={"days": days})


class Jobs:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def create(self, question: str, *, idempotency_key: str | None = None, **options: Any) -> Any:
        body = build_run_body(question=question, **options)
        return self._client._request("POST", "/v1/intelligence/jobs", json_body=body, idempotency_key=idempotency_key or f"sdk-{uuid.uuid4().hex}")

    def retrieve(self, job_id: str) -> Any:
        return self._client._request("GET", f"/v1/intelligence/jobs/{job_id}")

    def list(self, *, status: str | None = None, limit: int = 20) -> Any:
        params = {"limit": limit, **({"status": status} if status else {})}
        return self._client._request("GET", "/v1/intelligence/jobs", params=params)

    def cancel(self, job_id: str) -> Any:
        return self._client._request("POST", f"/v1/intelligence/jobs/{job_id}/cancel")

    def wait(self, job_id: str, *, timeout: float = 600.0, poll_interval: float = 2.0) -> Any:
        return self._client._wait(job_id, timeout=timeout, poll_interval=poll_interval)


class Sessions:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def create(self, *, title: str | None = None, context: dict[str, Any] | None = None,
               metadata: dict[str, str] | None = None, retention_days: int = 30) -> Any:
        body = {"title": title, "context": context, "metadata": metadata or {}, "retention_days": retention_days}
        return self._client._request("POST", "/v1/intelligence/sessions", json_body={k: v for k, v in body.items() if v is not None})

    def retrieve(self, session_id: str) -> Any:
        return self._client._request("GET", f"/v1/intelligence/sessions/{session_id}")

    def update(self, session_id: str, **changes: Any) -> Any:
        return self._client._request("PATCH", f"/v1/intelligence/sessions/{session_id}", json_body=changes)

    def list(self, *, limit: int = 20) -> Any:
        return self._client._request("GET", "/v1/intelligence/sessions", params={"limit": limit})

    def turns(self, session_id: str, *, limit: int = 50) -> Any:
        return self._client._request("GET", f"/v1/intelligence/sessions/{session_id}/turns", params={"limit": limit})

    def delete(self, session_id: str) -> Any:
        return self._client._request("DELETE", f"/v1/intelligence/sessions/{session_id}")


class Files:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def upload(self, file: str | os.PathLike | BinaryIO | bytes, *, filename: str | None = None,
               content_type: str | None = None, purpose: str = "attachment") -> Any:
        if isinstance(file, (str, os.PathLike)):
            path = os.fspath(file)
            with open(path, "rb") as handle:
                content = handle.read()
            filename = filename or os.path.basename(path)
        elif isinstance(file, bytes):
            content = file
        else:
            content = file.read()
            filename = filename or os.path.basename(getattr(file, "name", "") or "upload")
        files = {"file": (filename or "upload", content, content_type or guess_content_type(filename))}
        return self._client._request("POST", "/v1/intelligence/files", files=files, data={"purpose": purpose})

    def retrieve(self, file_id: str) -> Any:
        return self._client._request("GET", f"/v1/intelligence/files/{file_id}")

    def list(self, *, limit: int = 50) -> Any:
        return self._client._request("GET", "/v1/intelligence/files", params={"limit": limit})

    def delete(self, file_id: str) -> Any:
        return self._client._request("DELETE", f"/v1/intelligence/files/{file_id}")


class Knowledge:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def add(self, *, collection: str, title: str, text: str | None = None, file_id: str | None = None,
            external_id: str | None = None, source: dict[str, Any] | None = None, observed_at: str | None = None,
            metadata: dict[str, str] | None = None) -> Any:
        body = {"collection": collection, "title": title, "text": text, "file_id": file_id, "external_id": external_id,
                "source": source, "observed_at": observed_at, "metadata": metadata}
        return self._client._request("POST", "/v1/intelligence/knowledge/documents", json_body={k: v for k, v in body.items() if v is not None})

    def search(self, query: str, *, collections: list[str], max_results: int = 6) -> Any:
        return self._client._request("POST", "/v1/intelligence/knowledge/search", json_body={"query": query, "collections": collections, "max_results": max_results})

    def list(self, *, collection: str | None = None, limit: int = 50) -> Any:
        params = {"limit": limit, **({"collection": collection} if collection else {})}
        return self._client._request("GET", "/v1/intelligence/knowledge/documents", params=params)

    def collections(self) -> Any:
        return self._client._request("GET", "/v1/intelligence/knowledge/collections")

    def retrieve(self, document_id: str) -> Any:
        return self._client._request("GET", f"/v1/intelligence/knowledge/documents/{document_id}")

    def delete(self, document_id: str) -> Any:
        return self._client._request("DELETE", f"/v1/intelligence/knowledge/documents/{document_id}")


class Tools:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def list(self) -> Any:
        return self._client._request("GET", "/v1/intelligence/tools")

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._client._request("POST", "/v1/intelligence/tools/execute", json_body={"name": name, "arguments": arguments})


class Runs:
    def __init__(self, client: _Base) -> None:
        self._client = client

    def retrieve(self, run_id: str) -> Any:
        return self._client._request("GET", f"/v1/intelligence/runs/{run_id}")

    def list(self, *, limit: int = 20, execution: str | None = None, before: str | None = None) -> Any:
        """One page of runs, newest first. Pass the previous page's ``next_before`` as ``before``."""
        params: dict[str, Any] = {"limit": limit}
        if execution:
            params["execution"] = execution
        if before:
            params["before"] = before
        return self._client._request("GET", "/v1/intelligence/runs", params=params)

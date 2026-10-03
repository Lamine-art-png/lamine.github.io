"""Streaming request-body byte enforcement for Field Intelligence JSON routes.

A chunked (no ``Content-Length``) request must not be able to stream an
unbounded JSON body into Pydantic parsing. This ASGI middleware consumes body
chunks as they arrive, counting bytes, and terminates the request with 413 the
moment the configured limit is exceeded — the framework never assembles or
parses the payload. Memory use is bounded by the limit itself.

Multipart uploads are exempt here: media routes enforce their own per-asset
streaming cap (``FIELD_ASSET_MAX_BYTES``) chunk by chunk.
"""
from __future__ import annotations

import json

from app.core.config import settings


class FieldIntelligenceBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int | None = None, path_prefix: str = "/v1/field-intelligence") -> None:
        self.app = app
        self._max_bytes = max_bytes  # None -> read the live setting per request
        self.path_prefix = path_prefix

    @property
    def max_bytes(self) -> int:
        if self._max_bytes is not None:
            return int(self._max_bytes)
        return int(settings.FIELD_SYNC_MAX_BODY_BYTES)

    def _applies(self, scope) -> bool:
        if scope["type"] != "http":
            return False
        if scope.get("method", "").upper() not in {"POST", "PUT", "PATCH"}:
            return False
        if not scope.get("path", "").startswith(self.path_prefix):
            return False
        content_type = b""
        for name, value in scope.get("headers") or []:
            if name == b"content-type":
                content_type = value
                break
        return not content_type.lower().startswith(b"multipart/form-data")

    async def __call__(self, scope, receive, send) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return

        limit = self.max_bytes
        buffered: list[dict] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # disconnect while streaming: hand everything to the app as-is
                buffered.append(message)
                break
            received += len(message.get("body") or b"")
            if received > limit:
                body = json.dumps({"detail": "Request body too large"}).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        replay = iter(buffered)

        async def replay_receive():
            for message in replay:
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


class IntelligenceBodyLimitMiddleware:
    """Pass-through byte cap for ``/v1/intelligence*`` writes, multipart included.

    Unlike the JSON middleware above this never buffers: it counts bytes as
    the application reads them, rejects a declared ``Content-Length`` over the
    cap before reading anything, and cuts a chunked body off the moment it
    exceeds the cap (the application sees a disconnect; the client gets 413).
    Starlette would otherwise spool a whole multipart upload to disk before
    authentication or per-file limits run.
    """

    MULTIPART_MAX_BYTES = 16 * 1024 * 1024
    JSON_MAX_BYTES = 4 * 1024 * 1024

    # Only the Intelligence Platform surface; older /v1/intelligence/* product
    # routes keep their own limits.
    EXACT_PATHS = frozenset({"/v1/intelligence", "/v1/intelligence/jobs", "/v1/intelligence/files", "/v1/intelligence/sessions", "/v1/intelligence/tools/execute"})
    PATH_PREFIXES = ("/v1/intelligence/knowledge/", "/v1/intelligence/sessions/", "/v1/intelligence/jobs/")

    def __init__(self, app) -> None:
        self.app = app

    def _applies_to(self, path: str) -> bool:
        return path in self.EXACT_PATHS or path.startswith(self.PATH_PREFIXES)

    async def _reject(self, send) -> None:
        body = json.dumps({"detail": {"code": "request_too_large", "message": "Request body too large"}}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method", "").upper() not in {"POST", "PUT", "PATCH"}
            or not self._applies_to(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        multipart = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limit = self.MULTIPART_MAX_BYTES if multipart else self.JSON_MAX_BYTES
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        state = {"received": 0, "exceeded": False, "started": False}

        async def limited_receive():
            if state["exceeded"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body") or b"")
                if state["received"] > limit:
                    state["exceeded"] = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if state["exceeded"]:
                return  # the application's reaction to the cut-off is replaced by 413
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not state["exceeded"]:
                raise
        if state["exceeded"] and not state["started"]:
            await self._reject(send)

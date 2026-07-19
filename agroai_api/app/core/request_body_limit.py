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

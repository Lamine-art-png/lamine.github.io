from __future__ import annotations

import pytest
from fastapi import Request

from app.main import platform_request_metadata_log


def _request(receive):
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/v1/field-ops/tasks",
            "raw_path": b"/v1/field-ops/tasks",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_client_disconnect_no_response_is_not_an_asgi_error():
    async def receive():
        return {"type": "http.disconnect"}

    async def call_next(_request):
        raise RuntimeError("No response returned.")

    response = await platform_request_metadata_log(_request(receive), call_next)

    assert response.status_code == 499


@pytest.mark.asyncio
async def test_no_response_without_disconnect_still_raises():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def call_next(_request):
        raise RuntimeError("No response returned.")

    with pytest.raises(RuntimeError, match="No response returned"):
        await platform_request_metadata_log(_request(receive), call_next)

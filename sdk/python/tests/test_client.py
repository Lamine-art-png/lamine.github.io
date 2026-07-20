import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
import requests

import agroai_platform.client as client_module
from agroai_platform import (
    AgroAIPlatformClient,
    AgroAIPlatformError,
    ApiResponse,
    AsyncAgroAIPlatformClient,
    RateLimitMetadata,
    verify_webhook_signature,
)


def _response(
    status_code: int,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    response.headers.update(headers or {})
    response.url = "https://api.example.test/v1/platform/test"
    return response


def test_sync_client_separates_server_request_and_client_correlation_ids(monkeypatch):
    calls: list[dict] = []
    responses = iter(
        [
            _response(
                200,
                {"project": "one"},
                headers={
                    "X-Request-Id": "req_server_one",
                    "RateLimit-Limit": "100",
                    "RateLimit-Remaining": "99",
                    "RateLimit-Reset": "1234",
                },
            ),
            _response(200, {"project": "two"}, headers={"X-Request-Id": "req_server_two"}),
        ]
    )

    def fake_request(*args, **kwargs):
        calls.append({"args": args, **kwargs})
        return next(responses)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    client = AgroAIPlatformClient(api_key="agro_test_example", base_url="https://api.example.test")
    first = client.request("GET", "/v1/platform/me", client_correlation_id="customer-trace-42")
    second = client.request("GET", "/v1/platform/providers", client_correlation_id="customer-trace-42")

    assert first.request_id == "req_server_one"
    assert second.request_id == "req_server_two"
    assert first.request_id != second.request_id
    assert first.client_correlation_id == second.client_correlation_id == "customer-trace-42"
    assert [call["headers"]["X-Request-Id"] for call in calls] == ["customer-trace-42", "customer-trace-42"]
    assert first.rate_limit == RateLimitMetadata(limit=100, remaining=99, reset=1234, retry_after=None)


def test_sync_get_retry_reuses_only_correlation_metadata(monkeypatch):
    calls: list[dict] = []
    responses = iter(
        [
            _response(503, {"code": "temporary"}),
            _response(200, {"ok": True}, headers={"X-Request-Id": "req_final_attempt"}),
        ]
    )
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    def fake_request(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    result = AgroAIPlatformClient(api_key="agro_test_example").request("GET", "/v1/platform/me")

    assert len(calls) == 2
    correlations = [call["headers"]["X-Request-Id"] for call in calls]
    assert correlations[0] == correlations[1]
    assert correlations[0].startswith("corr_")
    assert result.request_id == "req_final_attempt"
    assert result.client_correlation_id == correlations[0]


def test_write_idempotency_and_typed_error_use_independent_server_id(monkeypatch):
    calls: list[dict] = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs)
        return _response(
            409,
            {"detail": {"code": "idempotency_conflict", "message": "payload conflict"}},
            headers={"X-Request-Id": "req_server_error"},
        )

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    client = AgroAIPlatformClient(api_key="agro_test_example")
    with pytest.raises(AgroAIPlatformError) as captured:
        client.request(
            "POST",
            "/v1/platform/fields",
            json={"name": "North"},
            idempotency_key="field-create-1",
            client_correlation_id="client-write-1",
        )

    assert len(calls) == 1
    assert calls[0]["headers"]["Idempotency-Key"] == "field-create-1"
    assert calls[0]["headers"]["X-Request-Id"] == "client-write-1"
    assert captured.value.status_code == 409
    assert captured.value.code == "idempotency_conflict"
    assert captured.value.request_id == "req_server_error"


def test_client_rejects_unbounded_correlation_and_missing_upload_url(monkeypatch):
    called = False

    def fake_request(*_args, **_kwargs):
        nonlocal called
        called = True
        return _response(200, {})

    monkeypatch.setattr(client_module.requests, "request", fake_request)
    client = AgroAIPlatformClient(api_key="agro_test_example")
    with pytest.raises(ValueError, match="client_correlation_id"):
        client.request("GET", "/v1/platform/me", client_correlation_id="contains spaces")
    assert called is False
    with pytest.raises(ValueError, match="upload_url"):
        client.upload_file({}, b"payload", content_type="application/octet-stream")


def test_field_iterator_follows_cursor_contract(monkeypatch):
    client = AgroAIPlatformClient(api_key="agro_test_example")
    cursors: list[str | None] = []

    def page(*, cursor=None, limit=50):
        cursors.append(cursor)
        data = (
            {"items": [{"id": "field-1"}], "next_cursor": "next"}
            if cursor is None
            else {"items": [{"id": "field-2"}], "next_cursor": None}
        )
        return ApiResponse(
            data=data,
            request_id=f"req_page_{len(cursors)}",
            client_correlation_id=f"corr_page_{len(cursors)}",
            rate_limit=RateLimitMetadata(),
        )

    monkeypatch.setattr(client, "list_fields", page)
    assert [item["id"] for item in client.iter_fields(page_size=500)] == ["field-1", "field-2"]
    assert cursors == [None, "next"]


def test_async_client_preserves_correlation_and_returns_server_request_id(monkeypatch):
    calls: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return httpx.Response(
                200,
                json={"ok": True},
                headers={"X-Request-Id": "req_async_server"},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)
    result = asyncio.run(
        AsyncAgroAIPlatformClient(api_key="agro_test_example").request(
            "GET",
            "/v1/platform/me",
            client_correlation_id="async-correlation",
        )
    )
    assert result.request_id == "req_async_server"
    assert result.client_correlation_id == "async-correlation"
    assert calls[0]["headers"]["X-Request-Id"] == "async-correlation"


def test_webhook_signature_and_replay_window():
    body = b'{"event":"field.updated"}'
    timestamp = "1000"
    secret = "whsec_test"
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(secret=secret, body=body, timestamp=timestamp, signature=f"v1={signature}", now=1001)
    assert not verify_webhook_signature(secret=secret, body=body, timestamp=timestamp, signature=f"v1={signature}", now=2000)
    assert not verify_webhook_signature(secret=secret, body=body + b"x", timestamp=timestamp, signature=f"v1={signature}", now=1001)
    assert not verify_webhook_signature(secret=secret, body=body, timestamp="not-a-time", signature=f"v1={signature}", now=1001)

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agroai import (
    AgroAI,
    AsyncAgroAI,
    ConflictError,
    InsufficientBalanceError,
    NotFoundError,
    RateLimitError,
    UnprocessableEntityError,
)


def _client(handler, **kwargs) -> AgroAI:
    return AgroAI(api_key="agro_live_test", base_url="https://api.test", http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_run_builds_contract_and_returns_attribute_objects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(200, json={"id": "run_1", "status": "completed", "structured_output": {"likely_causes": [{"name": "early blight"}]}})

    client = _client(handler)
    result = client.intelligence.run(
        "Why are leaves spotting?", task="field_diagnosis",
        context={"crop": {"name": "tomato"}}, response_format="diagnosis", knowledge=["agronomy"],
        attachments=["file_1"], tools=[{"name": "units.convert.v1", "arguments": {}}], metadata={"app": "scout"},
    )
    assert result.structured_output.likely_causes[0].name == "early blight"
    body = seen["body"]
    assert body["response_format"] == {"type": "agroai_schema", "name": "diagnosis"}
    assert body["knowledge"] == {"collections": ["agronomy"]}
    assert body["attachments"] == [{"file_id": "file_1"}]
    assert "input" not in body and "session_id" not in body, "unset options are omitted"
    assert seen["headers"]["Idempotency-Key"].startswith("sdk-")
    assert seen["headers"]["Authorization"] == "Bearer agro_live_test"


def test_custom_schema_shorthand():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "r"})

    _client(handler).intelligence.run("x?", response_format={"type": "object", "properties": {}})
    assert seen["body"]["response_format"] == {"type": "json_schema", "schema": {"type": "object", "properties": {}}}


def test_retries_reuse_the_same_idempotency_key(monkeypatch):
    monkeypatch.setattr("agroai._client.time.sleep", lambda _s: None)
    keys = []

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        if len(keys) < 3:
            return httpx.Response(503, json={"detail": {"code": "intelligence_temporarily_unavailable"}})
        return httpx.Response(200, json={"id": "run_1"})

    assert _client(handler).intelligence.run("x?").id == "run_1"
    assert len(keys) == 3 and len(set(keys)) == 1, "a retried paid request must carry one key"


def test_non_retryable_and_typed_errors(monkeypatch):
    monkeypatch.setattr("agroai._client.time.sleep", lambda _s: None)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        path = request.url.path
        if path.endswith("/pricing"):
            return httpx.Response(402, json={"detail": {"code": "insufficient_intelligence_balance", "required_cents": 50}})
        if path.endswith("/jobs/missing"):
            return httpx.Response(404, json={"detail": {"code": "intelligence_job_not_found"}}, headers={"X-Request-Id": "req_9"})
        if path.endswith("/usage"):
            return httpx.Response(429, json={"detail": {"code": "rate_limit_exceeded"}}, headers={"Retry-After": "0"})
        if path.endswith("/intelligence"):
            return httpx.Response(409, json={"detail": {"code": "idempotency_key_reused_with_different_request"}})
        return httpx.Response(422, json={"detail": [{"msg": "field required"}]})

    client = _client(handler)
    with pytest.raises(InsufficientBalanceError) as exc:
        client.intelligence.pricing()
    assert exc.value.required_cents == 50
    with pytest.raises(NotFoundError) as exc:
        client.intelligence.jobs.retrieve("missing")
    assert exc.value.request_id == "req_9"
    with pytest.raises(RateLimitError):
        client.intelligence.usage()
    before = len(calls)
    with pytest.raises(ConflictError):
        client.intelligence.run("x?")
    assert len(calls) == before + 1, "a changed-request conflict is never retried"
    with pytest.raises(UnprocessableEntityError):
        client.intelligence.sessions.create()


def test_stream_parses_server_sent_events():
    stream = (
        'event: run.created\ndata: {"id":"run_1"}\n\n'
        ": keep-alive\n\n"
        'event: context.ready\ndata: {"sources":2}\n\n'
        'event: run.completed\ndata: {"id":"run_1","status":"completed"}\n\n'
    )

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=stream.encode(), headers={"content-type": "text/event-stream"})

    events = list(_client(handler).intelligence.stream("x?"))
    assert [event.event for event in events] == ["run.created", "context.ready", "run.completed"]
    assert events[-1].data.status == "completed"


def test_job_wait_polls_until_terminal(monkeypatch):
    monkeypatch.setattr("agroai._client.time.sleep", lambda _s: None)
    states = iter(["queued", "running", "completed"])

    def handler(request):
        if request.method == "POST":
            return httpx.Response(202, json={"id": "job_1", "status": "queued"})
        return httpx.Response(200, json={"id": "job_1", "status": next(states)})

    client = _client(handler)
    job = client.intelligence.jobs.create("Season report", task="report")
    assert client.intelligence.jobs.wait(job.id).status == "completed"


def test_file_upload_is_multipart():
    seen = {}

    def handler(request):
        seen["ctype"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(201, json={"id": "file_1", "kind": "text"})

    uploaded = _client(handler).intelligence.files.upload(b"a,b\n1,2", filename="lab.csv", content_type="text/csv")
    assert uploaded.id == "file_1"
    assert seen["ctype"].startswith("multipart/form-data") and b"lab.csv" in seen["body"]


def test_async_client_run_and_stream():
    async def handler(request):
        if json.loads(request.content).get("stream"):
            return httpx.Response(200, content=b'event: run.completed\ndata: {"id":"r"}\n\n')
        return httpx.Response(200, json={"id": "r", "status": "completed"})

    async def main():
        async with AsyncAgroAI(api_key="k", base_url="https://api.test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
            result = await client.intelligence.run("x?")
            events = [event async for event in client.intelligence.stream("x?")]
            return result, events

    result, events = asyncio.run(main())
    assert result.status == "completed" and events[0].event == "run.completed"


def test_api_key_required(monkeypatch):
    monkeypatch.delenv("AGROAI_API_KEY", raising=False)
    with pytest.raises(Exception):
        AgroAI()


@pytest.mark.parametrize(
    ("filename", "explicit", "expected"),
    [
        ("notes.txt", None, "text/plain"),
        ("lab.CSV", None, "text/csv"),
        ("sop.md", None, "text/markdown"),
        ("records.json", None, "application/json"),
        ("report.pdf", None, "application/pdf"),
        ("leaf.JPG", None, "image/jpeg"),
        ("blob.bin", None, "application/octet-stream"),
        ("noext", None, "application/octet-stream"),
        ("notes.txt", "text/csv", "text/csv"),
    ],
)
def test_upload_infers_supported_types_and_preserves_explicit(filename, explicit, expected, tmp_path):
    seen = {}

    def handler(request):
        seen["body"] = request.content
        return httpx.Response(201, json={"id": "file_1"})

    path = tmp_path / filename
    path.write_bytes(b"a,b\n1,2\n")
    _client(handler).intelligence.files.upload(str(path), content_type=explicit)
    assert f"Content-Type: {expected}".encode() in seen["body"]

import httpx
import pytest

from app.adapters.talgil import (
    STATUS_CACHE_TTL_FAILURE_SECONDS,
    TalgilAdapter,
    TalgilRateLimitError,
)


@pytest.mark.asyncio
async def test_talgil_429_retry_after_seconds(monkeypatch):
    adapter = TalgilAdapter(api_url="https://dev.talgil.com/api", api_key="redacted")

    class _StubClient:
        async def get(self, path, params=None):
            return httpx.Response(
                429,
                headers={"Retry-After": "120"},
                text="Too Many Requests",
                request=httpx.Request("GET", f"https://dev.talgil.com/api{path}"),
            )

    monkeypatch.setattr(adapter, "_get_client", lambda: _StubClient())

    with pytest.raises(TalgilRateLimitError) as exc:
        await adapter.list_targets()

    assert exc.value.retry_after_seconds == 120
    assert adapter.last_diagnostic.upstream_status_code == 429
    assert adapter.last_diagnostic.retry_after_seconds == 120


@pytest.mark.asyncio
async def test_runtime_status_uses_cache(monkeypatch):
    adapter = TalgilAdapter(api_url="https://dev.talgil.com/api", api_key="redacted")
    calls = {"n": 0}

    async def _fake_list_targets():
        calls["n"] += 1
        return [{"id": "6115"}]

    monkeypatch.setattr(adapter, "list_targets", _fake_list_targets)

    first = await adapter.get_runtime_status(use_cache=True)
    second = await adapter.get_runtime_status(use_cache=True)

    assert first.live is True
    assert second.live is True
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_runtime_status_failure_cache_ttl(monkeypatch):
    adapter = TalgilAdapter(api_url="https://dev.talgil.com/api", api_key="redacted")
    calls = {"n": 0}

    async def _fake_list_targets():
        calls["n"] += 1
        raise RuntimeError("upstream down")

    clock = {"t": 1000.0}

    monkeypatch.setattr(adapter, "list_targets", _fake_list_targets)
    monkeypatch.setattr("app.adapters.talgil.time.monotonic", lambda: clock["t"])

    first = await adapter.get_runtime_status(use_cache=True)
    assert first.live is False

    clock["t"] += STATUS_CACHE_TTL_FAILURE_SECONDS - 1
    second = await adapter.get_runtime_status(use_cache=True)
    assert second.live is False

    clock["t"] += 2
    third = await adapter.get_runtime_status(use_cache=True)
    assert third.live is False

    assert calls["n"] == 2

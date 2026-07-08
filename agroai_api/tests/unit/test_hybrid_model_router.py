from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.live_intelligence import LiveIntelligence, _ollama_compatible_answer


def _configure(monkeypatch, **values):
    defaults = {
        "AI_PROVIDER": "ollama",
        "AI_BASE_URL": "https://local-ai.agroai-pilot.com",
        "AI_API_KEY": "",
        "AI_MODEL": "",
        "AI_FAST_MODEL": "qwen/qwen3.5-flash-02-23",
        "AI_REASONING_MODEL": "z-ai/glm-5.2",
        "AI_REPORT_MODEL": "z-ai/glm-5.2",
        "AI_LOCAL_BASE_URL": "https://ollama.agroai-pilot.com",
        "AI_LOCAL_MODEL": "qwen3.5:4b",
        "AI_LOCAL_CF_ACCESS_CLIENT_ID": "test-client-id",
        "AI_LOCAL_CF_ACCESS_CLIENT_SECRET": "test-client-secret",
        "AI_EDGE_BASE_URL": "https://local-ai.agroai-pilot.com",
        "AI_EDGE_MODEL": "@cf/zai-org/glm-4.7-flash",
        "AI_EDGE_AUTH_TOKEN": "test-edge-token",
        "AI_CHALLENGER_MODEL": "deepseek/deepseek-v4-pro",
        "AI_FREE_MODEL": "tencent/hy3:free",
        "AI_MODEL_FALLBACKS": "z-ai/glm-5.2,deepseek/deepseek-v4-pro,tencent/hy3:free",
        "AI_ROUTING_MODE": "hybrid",
        "AI_MODEL_TEST_COMMANDS_ENABLED": True,
        "AI_LOCAL_NUM_CTX": 6144,
        "AI_LOCAL_MAX_TOKENS": 1200,
        "AI_LOCAL_TIMEOUT_SECONDS": 90,
        "AI_LOCAL_THINKING": False,
        "AI_EDGE_TIMEOUT_SECONDS": 45,
        "AI_TIMEOUT_SECONDS": 60,
    }
    defaults.update(values)
    for key, value in defaults.items():
        monkeypatch.setattr(settings, key, value)


def test_hybrid_routes_edge_first_for_fast_and_remote_first_for_reasoning(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.auto_order("fast") == ["edge", "local", "remote"]
    assert runtime.auto_order("reasoning") == ["remote", "edge", "local"]
    assert runtime.auto_order("report") == ["remote", "edge", "local"]
    assert runtime.auto_order("deep") == ["remote", "edge", "local"]


def test_explicit_test_commands_select_exact_lanes(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.parse_test_route("/local diagnose this field") == ("local", "diagnose this field")
    assert runtime.parse_test_route("/edge diagnose this field") == ("edge", "diagnose this field")
    assert runtime.parse_test_route("/glm diagnose this field") == ("glm", "diagnose this field")
    assert runtime.parse_test_route("/deepseek diagnose this field") == ("challenger", "diagnose this field")
    assert runtime.parse_test_route("/free diagnose this field") == ("free", "diagnose this field")
    assert runtime.parse_test_route("/auto diagnose this field") == ("auto", "diagnose this field")


def test_test_commands_are_literal_user_text_when_disabled(monkeypatch):
    _configure(monkeypatch, AI_MODEL_TEST_COMMANDS_ENABLED=False)
    runtime = LiveIntelligence()

    assert runtime.parse_test_route("/glm diagnose this field") == ("auto", "/glm diagnose this field")


def test_forced_glm_is_exact_even_from_fast_profile(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.models("fast", "openrouter", "glm") == ["z-ai/glm-5.2"]
    assert runtime.models("fast", "openrouter", "primary") == ["qwen/qwen3.5-flash-02-23"]


def test_primary_challenger_and_free_routes_do_not_silently_fallback(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.models("reasoning", "openrouter", "primary") == ["z-ai/glm-5.2"]
    assert runtime.models("reasoning", "openrouter", "challenger") == ["deepseek/deepseek-v4-pro"]
    assert runtime.models("reasoning", "openrouter", "free") == ["tencent/hy3:free"]


def test_auto_remote_chain_preserves_primary_then_challenger_then_free(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    candidates = runtime.models("reasoning", "openrouter", "auto")
    assert candidates[:3] == [
        "z-ai/glm-5.2",
        "deepseek/deepseek-v4-pro",
        "tencent/hy3:free",
    ]
    assert len(candidates) == len(set(candidates))


def test_frontier_models_use_vendor_recommended_high_temperature(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.remote_temperature("z-ai/glm-5.2", "reasoning") == 1.0
    assert runtime.remote_temperature("deepseek/deepseek-v4-pro", "reasoning") == 1.0
    assert runtime.remote_temperature("qwen/qwen3.5-flash-02-23", "fast") == 0.2


def test_ollama_mode_can_use_openrouter_as_remote_frontier_lane(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    runtime = LiveIntelligence()

    assert runtime.remote() == ("https://openrouter.ai/api/v1", "test-key", "openrouter")
    assert runtime.ollama_model() == "qwen3.5:4b"
    assert runtime.local_base == "https://ollama.agroai-pilot.com"
    assert runtime.edge() == ("https://local-ai.agroai-pilot.com", "@cf/zai-org/glm-4.7-flash")


def test_known_production_local_ai_hostname_is_edge_not_mac(monkeypatch):
    _configure(
        monkeypatch,
        AI_LOCAL_BASE_URL="",
        AI_EDGE_BASE_URL="",
        AI_BASE_URL="https://local-ai.agroai-pilot.com",
    )
    runtime = LiveIntelligence()

    assert runtime.local_base == ""
    assert runtime.ollama_model() is None
    assert runtime.edge() == ("https://local-ai.agroai-pilot.com", "@cf/zai-org/glm-4.7-flash")


def test_non_edge_legacy_ollama_base_remains_local_compatible(monkeypatch):
    _configure(
        monkeypatch,
        AI_LOCAL_BASE_URL="",
        AI_EDGE_BASE_URL="",
        AI_BASE_URL="https://legacy-ollama.example.test",
    )
    runtime = LiveIntelligence()

    assert runtime.local_base == "https://legacy-ollama.example.test"
    assert runtime.ollama_model() == "qwen3.5:4b"
    assert runtime.edge() is None


def test_public_local_origin_fails_closed_without_cloudflare_access_token(monkeypatch):
    _configure(
        monkeypatch,
        AI_LOCAL_CF_ACCESS_CLIENT_ID="",
        AI_LOCAL_CF_ACCESS_CLIENT_SECRET="",
    )
    runtime = LiveIntelligence()

    assert runtime.local_requires_access() is True
    assert runtime.local_access_configured() is False
    assert runtime.ollama_model() is None


def test_loopback_local_origin_does_not_require_cloudflare_access(monkeypatch):
    _configure(
        monkeypatch,
        AI_LOCAL_BASE_URL="http://127.0.0.1:11434",
        AI_LOCAL_CF_ACCESS_CLIENT_ID="",
        AI_LOCAL_CF_ACCESS_CLIENT_SECRET="",
    )
    runtime = LiveIntelligence()

    assert runtime.local_requires_access() is False
    assert runtime.ollama_model() == "qwen3.5:4b"


def test_cloudflare_access_headers_are_attached_to_public_local_requests(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "secured local answer"}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self.headers = kwargs.get("headers")
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.live_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        runtime.run_local(
            "qwen3.5:4b",
            [{"role": "user", "content": "test"}],
            "fast",
        )
    )

    assert result == ("secured local answer", "qwen3.5:4b")
    assert fake_client.headers == {
        "CF-Access-Client-Id": "test-client-id",
        "CF-Access-Client-Secret": "test-client-secret",
    }


def test_edge_bearer_header_is_attached_to_workers_ai_requests(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "provider": "cloudflare-workers-ai",
                "model": "@cf/zai-org/glm-4.7-flash",
                "message": {"content": '{"answer":"secured edge answer"}'},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self.headers = kwargs.get("headers")
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.live_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        runtime.run_edge(
            ("https://local-ai.agroai-pilot.com", "@cf/zai-org/glm-4.7-flash"),
            [{"role": "user", "content": "test"}],
            "fast",
        )
    )

    assert result == ("secured edge answer", "@cf/zai-org/glm-4.7-flash")
    assert fake_client.headers == {"Authorization": "Bearer test-edge-token"}


def test_edge_wrapper_json_is_unwrapped_before_customer_response():
    body = {
        "provider": "cloudflare-workers-ai",
        "model": "@cf/zai-org/glm-4.7-flash",
        "message": {"role": "assistant", "content": '{"answer":"Irrigate only after checking ET and soil moisture."}'},
    }

    assert _ollama_compatible_answer(body) == "Irrigate only after checking ET and soil moisture."


def test_remote_account_credit_failure_stops_after_one_model(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    class FakeResponse:
        status_code = 402

    class FakeClient:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.live_intelligence.httpx.AsyncClient",
        lambda *args, **kwargs: fake_client,
    )

    result = asyncio.run(
        runtime.run_remote(
            ("https://openrouter.ai/api/v1", "test-key", "openrouter"),
            ["z-ai/glm-5.2", "deepseek/deepseek-v4-pro"],
            [{"role": "user", "content": "test"}],
            "reasoning",
        )
    )

    assert result is None
    assert fake_client.calls == 1


def test_local_resource_budget_is_clamped_for_eight_gb_class_machine(monkeypatch):
    _configure(
        monkeypatch,
        AI_LOCAL_NUM_CTX=999999,
        AI_LOCAL_MAX_TOKENS=999999,
        AI_LOCAL_TIMEOUT_SECONDS=999999,
    )
    runtime = LiveIntelligence()

    assert runtime.local_num_ctx == 16384
    assert runtime.local_max_tokens == 2800
    assert runtime.local_timeout == 180


def test_invalid_routing_mode_falls_back_to_hybrid(monkeypatch):
    _configure(monkeypatch, AI_ROUTING_MODE="definitely-not-valid")
    runtime = LiveIntelligence()

    assert runtime.routing_mode == "hybrid"
    assert runtime.auto_order("fast") == ["edge", "local", "remote"]
    assert runtime.auto_order("reasoning") == ["remote", "edge", "local"]

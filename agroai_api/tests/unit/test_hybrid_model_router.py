from __future__ import annotations

from app.core.config import settings
from app.services.live_intelligence import LiveIntelligence


def _configure(monkeypatch, **values):
    defaults = {
        "AI_PROVIDER": "ollama",
        "AI_BASE_URL": "https://local-ai.agroai-pilot.com",
        "AI_API_KEY": "",
        "AI_MODEL": "",
        "AI_FAST_MODEL": "qwen/qwen3.5-flash-02-23",
        "AI_REASONING_MODEL": "z-ai/glm-5.2",
        "AI_REPORT_MODEL": "z-ai/glm-5.2",
        "AI_LOCAL_MODEL": "qwen3.5:4b",
        "AI_CHALLENGER_MODEL": "deepseek/deepseek-v4-pro",
        "AI_FREE_MODEL": "tencent/hy3:free",
        "AI_MODEL_FALLBACKS": "z-ai/glm-5.2,deepseek/deepseek-v4-pro,tencent/hy3:free",
        "AI_ROUTING_MODE": "hybrid",
        "AI_MODEL_TEST_COMMANDS_ENABLED": True,
        "AI_LOCAL_NUM_CTX": 6144,
        "AI_LOCAL_MAX_TOKENS": 1200,
        "AI_LOCAL_TIMEOUT_SECONDS": 90,
        "AI_LOCAL_THINKING": False,
        "AI_TIMEOUT_SECONDS": 60,
    }
    defaults.update(values)
    for key, value in defaults.items():
        monkeypatch.setattr(settings, key, value)


def test_hybrid_routes_fast_local_first_and_reasoning_remote_first(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.auto_order("fast") == ["local", "remote"]
    assert runtime.auto_order("reasoning") == ["remote", "local"]
    assert runtime.auto_order("report") == ["remote", "local"]
    assert runtime.auto_order("deep") == ["remote", "local"]


def test_explicit_test_commands_select_exact_lanes(monkeypatch):
    _configure(monkeypatch)
    runtime = LiveIntelligence()

    assert runtime.parse_test_route("/local diagnose this field") == ("local", "diagnose this field")
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
    assert runtime.auto_order("fast") == ["local", "remote"]
    assert runtime.auto_order("reasoning") == ["remote", "local"]

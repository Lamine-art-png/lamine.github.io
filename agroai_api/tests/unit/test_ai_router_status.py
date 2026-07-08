from __future__ import annotations

import asyncio

from app.api.v1.ai_stable import ai_router_status
from app.core.config import settings


def test_ai_router_status_exposes_distinct_secret_free_lanes(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "AI_BASE_URL", "https://local-ai.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    monkeypatch.setattr(settings, "AI_MODEL", "")
    monkeypatch.setattr(settings, "AI_REASONING_MODEL", "z-ai/glm-5.2")
    monkeypatch.setattr(settings, "AI_REPORT_MODEL", "z-ai/glm-5.2")
    monkeypatch.setattr(settings, "AI_FAST_MODEL", "qwen/qwen3.5-flash-02-23")
    monkeypatch.setattr(settings, "AI_LOCAL_BASE_URL", "https://ollama.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_LOCAL_MODEL", "qwen3.5:4b")
    monkeypatch.setattr(settings, "AI_LOCAL_CF_ACCESS_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "AI_LOCAL_CF_ACCESS_CLIENT_SECRET", "super-secret")
    monkeypatch.setattr(settings, "AI_EDGE_BASE_URL", "https://local-ai.agroai-pilot.com")
    monkeypatch.setattr(settings, "AI_EDGE_MODEL", "@cf/zai-org/glm-4.7-flash")
    monkeypatch.setattr(settings, "AI_CHALLENGER_MODEL", "deepseek/deepseek-v4-pro")
    monkeypatch.setattr(settings, "AI_FREE_MODEL", "")
    monkeypatch.setattr(settings, "AI_MODEL_FALLBACKS", "z-ai/glm-5.2")
    monkeypatch.setattr(settings, "AI_ROUTING_MODE", "hybrid")
    monkeypatch.setattr(settings, "AI_MODEL_TEST_COMMANDS_ENABLED", True)

    payload = asyncio.run(ai_router_status())

    assert payload["routing_mode"] == "hybrid"
    assert payload["lanes"]["edge"]["provider"] == "cloudflare-workers-ai"
    assert payload["lanes"]["edge"]["model"] == "@cf/zai-org/glm-4.7-flash"
    assert payload["lanes"]["local"]["provider"] == "ollama"
    assert payload["lanes"]["local"]["model"] == "qwen3.5:4b"
    assert payload["lanes"]["local"]["access_required"] is True
    assert payload["lanes"]["local"]["access_configured"] is True
    assert payload["lanes"]["hosted"]["primary"] == "z-ai/glm-5.2"
    assert "super-secret" not in str(payload)
    assert "client-id" not in str(payload)

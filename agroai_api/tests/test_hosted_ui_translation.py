import json

import pytest

from app.services.ai_gateway import AIGatewayResult
from app.services.hosted_ui_translation import _json_catalog_content, _openrouter_key
from app.services import model_router as model_router_module


def test_hosted_translation_preserves_arbitrary_catalog_keys():
    body = {
        "choices": [
            {
                "message": {
                    "content": "```json\n{\"settings\":\"Ρυθμίσεις\",\"literal.paywall.title\":\"Αναβάθμιση\"}\n```"
                }
            }
        ]
    }
    parsed = json.loads(_json_catalog_content(body))
    assert parsed == {
        "settings": "Ρυθμίσεις",
        "literal.paywall.title": "Αναβάθμιση",
    }


@pytest.mark.asyncio
async def test_ollama_translation_failure_falls_back_to_hosted(monkeypatch):
    monkeypatch.setattr(model_router_module.settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(model_router_module.settings, "AI_BASE_URL", "https://local-ai.invalid")
    monkeypatch.setattr(model_router_module.settings, "AI_LOCAL_MODEL", "qwen3:1.7b")
    monkeypatch.setattr(model_router_module.settings, "AI_API_KEY", "")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def fake_local(**kwargs):
        return AIGatewayResult(
            status="unavailable",
            content="",
            provider="ollama",
            model="qwen3:1.7b",
            error="local origin unavailable",
        )

    async def fake_hosted(**kwargs):
        return AIGatewayResult(
            status="ok",
            content='{"settings":"Ρυθμίσεις"}',
            provider="openrouter",
            model="qwen/qwen3-next-80b-a3b-instruct",
        )

    monkeypatch.setattr(model_router_module, "run_local_ui_translation", fake_local)
    monkeypatch.setattr(model_router_module, "run_hosted_ui_translation", fake_hosted)

    router = model_router_module.ModelRouter()
    result, selection = await router.run(
        task="ui_translation",
        messages=[{"role": "user", "content": "Translate the catalog"}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    assert result.status == "ok"
    assert result.provider == "openrouter"
    assert json.loads(result.content) == {"settings": "Ρυθμίσεις"}
    assert selection.model == "qwen/qwen3-next-80b-a3b-instruct"


@pytest.mark.asyncio
async def test_configured_hosted_translation_runs_before_dead_local_origin(monkeypatch):
    monkeypatch.setattr(model_router_module.settings, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(model_router_module.settings, "AI_BASE_URL", "https://local-ai.invalid")
    monkeypatch.setattr(model_router_module.settings, "AI_LOCAL_MODEL", "qwen3:1.7b")
    monkeypatch.setattr(model_router_module.settings, "AI_API_KEY", "configured-openrouter-key")
    calls: list[str] = []

    async def fake_hosted(**kwargs):
        calls.append("hosted")
        return AIGatewayResult(
            status="ok",
            content='{"settings":"Ρυθμίσεις"}',
            provider="openrouter",
            model="qwen/qwen3-next-80b-a3b-instruct",
        )

    async def fake_local(**kwargs):
        calls.append("local")
        raise AssertionError("local fallback must not run after hosted success")

    monkeypatch.setattr(model_router_module, "run_hosted_ui_translation", fake_hosted)
    monkeypatch.setattr(model_router_module, "run_local_ui_translation", fake_local)

    router = model_router_module.ModelRouter()
    result, selection = await router.run(
        task="ui_translation",
        messages=[{"role": "user", "content": "Translate the catalog"}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    assert result.status == "ok"
    assert result.provider == "openrouter"
    assert selection.model == "qwen/qwen3-next-80b-a3b-instruct"
    assert calls == ["hosted"]


def test_non_openrouter_provider_key_is_not_reused_as_openrouter_credential(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(model_router_module.settings, "AI_PROVIDER", "openai-compatible")
    monkeypatch.setattr(model_router_module.settings, "AI_BASE_URL", "https://example-provider.invalid/v1")
    monkeypatch.setattr(model_router_module.settings, "AI_API_KEY", "another-provider-key")
    assert _openrouter_key() == ""


@pytest.mark.asyncio
async def test_ui_translation_uses_edge_cascade_for_non_ollama_primary(monkeypatch):
    monkeypatch.setattr(model_router_module.settings, "AI_PROVIDER", "openai-compatible")
    monkeypatch.setattr(model_router_module.settings, "AI_BASE_URL", "https://primary.invalid/v1")
    monkeypatch.setattr(model_router_module.settings, "AI_API_KEY", "primary-provider-key")
    monkeypatch.setattr(model_router_module.settings, "AI_EDGE_BASE_URL", "https://edge.invalid")
    monkeypatch.setattr(model_router_module.settings, "AI_EDGE_MODEL", "@cf/zai-org/glm-4.7-flash")
    calls: list[str] = []

    async def fake_edge(**kwargs):
        calls.append("edge")
        return AIGatewayResult(
            status="ok",
            content='{"settings":"Configuración"}',
            provider="cloudflare-workers-ai",
            model="@cf/zai-org/glm-4.7-flash",
        )

    async def fake_hosted(**kwargs):
        calls.append("hosted")
        raise AssertionError("hosted lane must not run after edge success")

    monkeypatch.setattr(model_router_module, "run_local_ui_translation", fake_edge)
    monkeypatch.setattr(model_router_module, "run_hosted_ui_translation", fake_hosted)

    router = model_router_module.ModelRouter()
    result, selection = await router.run(
        task="ui_translation",
        messages=[{"role": "user", "content": "Translate the catalog"}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    assert result.status == "ok"
    assert result.provider == "cloudflare-workers-ai"
    assert json.loads(result.content) == {"settings": "Configuración"}
    assert selection.model == "@cf/zai-org/glm-4.7-flash"
    assert calls == ["edge"]

import json

import pytest

from app.services.ai_gateway import AIGatewayResult
from app.services.hosted_ui_translation import _json_catalog_content
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

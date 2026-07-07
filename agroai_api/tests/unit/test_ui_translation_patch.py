import json

import pytest

from app.services.ai_gateway import AIGatewayResult
from app.services.model_router import ModelRouter, ModelSelection
from app.services.ui_translation_fallback import TranslationFallbackResult
import app.services.ui_translation_patch as patch


@pytest.mark.asyncio
async def test_ui_translation_fails_over_when_primary_provider_is_unavailable(monkeypatch):
    async def primary(self, **kwargs):
        return (
            AIGatewayResult(
                status="unavailable",
                content="",
                provider="ollama",
                model="qwen3:1.7b",
                error="origin unavailable",
            ),
            ModelSelection(task="ui_translation", profile="fast", model="qwen3:1.7b"),
        )

    async def fallback(locale, source):
        assert locale == "de"
        assert source == {"language": "Language", "save": "Save"}
        return TranslationFallbackResult(
            catalog={"language": "Sprache", "save": "Speichern"},
            provider="translation-fallback",
            model="test",
        )

    monkeypatch.setattr(patch, "_ORIGINAL", primary)
    monkeypatch.setattr(patch, "translate_ui_mapping", fallback)

    result, _selection = await patch._run(
        ModelRouter(),
        task="ui_translation",
        messages=[
            {"role": "system", "content": "Translate every JSON string value into German (de)."},
            {"role": "user", "content": json.dumps({"language": "Language", "save": "Save"})},
        ],
        response_format={"type": "json_object"},
    )

    assert result.status == "ok"
    assert result.provider == "translation-fallback"
    assert json.loads(result.content) == {"language": "Sprache", "save": "Speichern"}


def test_patch_is_installed_by_backend_startup_hook():
    patch.install_ui_translation_patch()
    assert getattr(ModelRouter, "_ui_translation_patch", False) is True

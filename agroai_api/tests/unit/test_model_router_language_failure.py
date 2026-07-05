import asyncio

from app.services.live_intelligence import LiveIntelligence, LiveResult
from app.services.model_router import ModelRouter


def test_model_router_preserves_language_generation_failed(monkeypatch):
    async def failed_run(_self, _task, _question, _messages, _preferred_language):
        return LiveResult(
            status="language_generation_failed",
            content="",
            provider="provider-a",
            model="model-a",
            response_language="fr",
            profile="reasoning",
            error="repair failed",
        )

    monkeypatch.setattr(LiveIntelligence, "run", failed_run)
    result, selection = asyncio.run(ModelRouter().run(
        task="chat",
        messages=[
            {"role": "user", "content": "Exact current question: Peux-tu vérifier les preuves manquantes ?\nPreferred portal language code: fr-FR"},
        ],
    ))

    assert result.status == "language_generation_failed"
    assert result.content == ""
    assert result.error == "repair failed"
    assert result.raw["response_language"] == "fr"
    assert selection.model == "model-a"

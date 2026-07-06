import asyncio

from app.services.language import language_matches_target, resolve_language
from app.services.live_intelligence import LiveIntelligence


def test_explicit_spanish_request_wins_over_french_portal():
    decision = resolve_language("fr-FR", "Réponds en espagnol : quelles données manquent ?")
    assert decision.response_code == "es"
    assert decision.explicit_code == "es"


def test_ambiguous_cyrillic_falls_back_to_portal_preference():
    decision = resolve_language("fr-FR", "Привет")
    assert decision.detected_code is None
    assert decision.response_code == "fr"


def test_clear_message_language_precedes_portal_preference():
    spanish = resolve_language("fr-FR", "¿Puedes revisar los datos de riego para el Bloque 7?")
    french = resolve_language("en", "Peux-tu vérifier les preuves manquantes pour l’irrigation ?")
    english = resolve_language("fr-FR", "Can you review the missing irrigation evidence for Block 7?")
    assert spanish.response_code == "es"
    assert french.response_code == "fr"
    assert english.response_code == "en"


def test_agricultural_technical_tokens_do_not_force_english():
    decision = resolve_language(
        "fr-FR",
        "Peux-tu vérifier les données John Deere, WiseConn, SGMA, ETc, ETo, NDVI, VWC, kPa et acre-ft pour le bloc 7 ?",
    )
    assert decision.response_code == "fr"


def test_ambiguous_markdown_is_not_a_confident_mismatch():
    assert language_matches_target("## ET summary\n- Block 7: 24 mm\n- [evidence-7]", "fr")


def test_failed_language_repair_returns_none(monkeypatch):
    async def wrong_language_remote(*_args, **_kwargs):
        return "This answer is still in English with field evidence.", "model-a"

    engine = LiveIntelligence()
    monkeypatch.setattr(engine, "run_remote", wrong_language_remote)
    repaired = asyncio.run(engine.repair(
        ("endpoint", "credential", "provider"),
        "model-a",
        "This answer is in English with field evidence.",
        "fr",
        "French",
    ))
    assert repaired is None


def test_failed_language_generation_never_returns_fake_answer(monkeypatch):
    async def wrong_language_remote(*_args, **_kwargs):
        return "This field report says the water evidence is missing and should be reviewed.", "model-a"

    engine = LiveIntelligence()
    monkeypatch.setattr(engine, "remote", lambda: ("endpoint", "credential", "provider"))
    monkeypatch.setattr(engine, "models", lambda _profile, _provider: ["model-a"])
    monkeypatch.setattr(engine, "run_remote", wrong_language_remote)
    result = asyncio.run(engine.run(
        "chat",
        "Peux-tu vérifier les preuves manquantes ?",
        [{"role": "user", "content": "Peux-tu vérifier les preuves manquantes ?"}],
        "fr-FR",
    ))
    assert result.status == "language_generation_failed"
    assert result.content == ""
    assert result.error

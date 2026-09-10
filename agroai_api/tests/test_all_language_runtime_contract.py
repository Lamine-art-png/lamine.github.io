import json
from pathlib import Path

from app.api.v1.voice import VoiceCallRequest, _instructions
from app.services.language import resolve_language
from app.services.language_registry import family_name, language_root


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUPPORTED = json.loads((_REPO_ROOT / "shared" / "supported-locales.json").read_text(encoding="utf-8"))


def test_every_enabled_ui_locale_drives_ask_and_voice_language_contract():
    for locale in _SUPPORTED["enabledUiLocales"]:
        if locale == "auto":
            continue
        root = language_root(locale)
        expected_name = family_name(root)

        decision = resolve_language(locale, "")
        assert decision.response_code == root, locale
        assert expected_name in decision.instruction, locale

        payload = VoiceCallRequest(
            sdp="v=0\\r\\no=- 0 0 IN IP4 127.0.0.1\\r\\ns=AGRO-AI",
            language=locale,
        )
        instruction = _instructions(payload)
        assert expected_name in instruction, locale


def test_auto_language_contract_never_forces_english():
    decision = resolve_language("auto", "")
    assert decision.response_code == "auto"
    assert "same natural language" in decision.instruction

    payload = VoiceCallRequest(
        sdp="v=0\\r\\no=- 0 0 IN IP4 127.0.0.1\\r\\ns=AGRO-AI",
        language="auto",
    )
    assert "user's language automatically" in _instructions(payload)

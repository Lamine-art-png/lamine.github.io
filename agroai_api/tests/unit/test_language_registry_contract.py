from app.services.language import detect_language_hint, resolve_language
from app.services.language_registry import (
    all_ai_response_families,
    enabled_ui_locales,
    family_direction,
    family_name,
    family_supported,
    language_families,
    locale_specs,
    normalize_bcp47,
)


def test_every_declared_ai_family_is_loadable_from_shared_registry():
    families = all_ai_response_families()
    assert len(families) >= 50
    assert len(families) == len(set(families))
    for code in families:
        assert family_supported(code)
        assert family_name(code)
        assert language_families()[code].code == code


def test_ui_scope_remains_separate_from_ai_response_scope():
    assert enabled_ui_locales() == ("auto", "en", "fr-FR")
    assert len(all_ai_response_families()) > len(enabled_ui_locales())
    assert "ar" in all_ai_response_families()
    assert "ja" in all_ai_response_families()
    assert "sw" in all_ai_response_families()


def test_bcp47_normalization_preserves_region_and_script_shape():
    assert normalize_bcp47("fr_ca") == "fr-CA"
    assert normalize_bcp47("zh_hant_tw") == "zh-Hant-TW"
    assert normalize_bcp47("PT_br") == "pt-BR"


def test_manifest_locale_fallback_graph_is_available_to_runtime():
    specs = locale_specs()
    assert specs["fr-ca"].language_code == "fr"
    assert specs["fr-ca"].fallback_chain == ("fr", "fr-FR", "en")
    assert specs["ar"].direction == "rtl"


def test_auto_unknown_language_never_silently_defaults_to_english():
    decision = resolve_language("auto", "Привет")
    assert decision.detected_code is None
    assert decision.response_code == "auto"
    assert "same natural language" in decision.instruction
    assert "Do not default to English" in decision.instruction


def test_selected_supported_family_can_drive_response_without_ui_catalog():
    decision = resolve_language("de-DE", "ETc 6.3 mm/day; NDVI 0.71")
    assert decision.selected_code == "de"
    assert decision.response_code == "de"
    assert decision.response_name == "German"


def test_explicit_language_request_overrides_portal_language_across_registry():
    decision = resolve_language("fr-FR", "Please answer in Ukrainian and preserve ETc 6.3 mm/day.")
    assert decision.explicit_code == "uk"
    assert decision.response_code == "uk"
    assert decision.response_name == "Ukrainian"


def test_unambiguous_scripts_map_to_registered_families():
    samples = {
        "日本語で答えてください": "ja",
        "한국어로 답해주세요": "ko",
        "বাংলায় উত্তর দিন": "bn",
        "தமிழில் பதிலளிக்கவும்": "ta",
        "తెలుగులో సమాధానం ఇవ్వండి": "te",
        "ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸಿ": "kn",
        "ภาษาไทย": "th",
        "ქართული": "ka",
        "Հայերեն": "hy",
        "Ελληνικά": "el",
    }
    for text, expected in samples.items():
        detected, _ = detect_language_hint(text)
        assert detected == expected


def test_shared_scripts_remain_ambiguous_instead_of_misclassification():
    for text in ("Привет", "مرحبا", "नमस्ते"):
        detected, label = detect_language_hint(text)
        assert detected is None
        assert label


def test_rtl_direction_comes_from_family_registry():
    for code in ("ar", "fa", "ur"):
        assert family_direction(code) == "rtl"
    assert family_direction("fr") == "ltr"

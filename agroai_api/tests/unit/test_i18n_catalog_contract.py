from app.api.v1.i18n import _enabled_locale_payloads, _validate_translated_catalog
from app.services.language_registry import enabled_ui_locales


def test_language_discovery_exposes_every_enabled_ui_locale():
    payloads = _enabled_locale_payloads()
    assert [item["code"] for item in payloads] == list(enabled_ui_locales())
    assert len(payloads) >= 50


def test_generated_catalog_requires_exact_key_parity():
    source = {"language": "Language", "save": "Save"}
    assert _validate_translated_catalog(source, {"language": "Sprache", "save": "Speichern"}) == {
        "language": "Sprache",
        "save": "Speichern",
    }

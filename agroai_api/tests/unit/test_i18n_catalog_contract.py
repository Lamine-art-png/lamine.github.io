import pytest

from app.api.v1.i18n import CatalogRequest, _chunks, _decode_json_object, _enabled_locale_payloads, _validate_translated_catalog, canonical_source_catalog
from app.services.language_registry import enabled_ui_locales


def test_language_discovery_exposes_every_enabled_ui_locale():
    payloads = _enabled_locale_payloads()
    assert [item["code"] for item in payloads] == list(enabled_ui_locales())
    assert len(payloads) >= 50


def test_canonical_catalog_is_accepted_by_request_contract():
    source = canonical_source_catalog()
    payload = CatalogRequest(locale="de", source=source)
    assert payload.source == source
    assert source["language"] == "Language"


def test_translation_chunks_preserve_exact_source_union():
    source = canonical_source_catalog()
    chunks = _chunks(source)
    rebuilt = {}
    for chunk in chunks:
        assert 1 <= len(chunk) <= 48
        rebuilt.update(chunk)
    assert rebuilt == source
    assert len(chunks) >= 2


def test_decode_json_object_accepts_fenced_model_output():
    assert _decode_json_object('```json\n{"language":"Sprache"}\n```') == {"language": "Sprache"}


def test_generated_catalog_requires_exact_key_parity():
    source = {"language": "Language", "save": "Save"}
    assert _validate_translated_catalog(source, {"language": "Sprache", "save": "Speichern"}) == {
        "language": "Sprache",
        "save": "Speichern",
    }


def test_generated_catalog_preserves_placeholder_multiset():
    source = {
        "notice": "Report emailed to {recipient}.",
        "action": "Action completed: {title}",
        "risk": "{level} risk",
    }
    translated = {
        "notice": "Bericht an {recipient} gesendet.",
        "action": "Aktion abgeschlossen: {title}",
        "risk": "Risiko {level}",
    }
    assert _validate_translated_catalog(source, translated) == translated


@pytest.mark.parametrize(
    "translated_value",
    [
        "Sent.",
        "Sent to {target}.",
        "Sent to {recipient} and {recipient}.",
        "Sent to " + "{" + "{recipient}" + "}" + ".",
        "Sent to " + "{recipient}" + "}" + ".",
        "Sent to " + "{" + "{recipient}" + ".",
        "Sent to " + "{recipient" + ".",
        "Sent to " + "recipient}" + ".",
    ],
)
def test_generated_catalog_rejects_changed_or_malformed_placeholders(translated_value):
    source = {"notice": "Report emailed to {recipient}."}
    with pytest.raises(ValueError, match="placeholders"):
        _validate_translated_catalog(source, {"notice": translated_value})

import pytest

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

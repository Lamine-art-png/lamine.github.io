import pytest
from fastapi import HTTPException

from app.api.v1.i18n import (
    CatalogRequest,
    _canonical_enabled_locale,
    _chunks,
    _decode_json_object,
    _enabled_locale_payloads,
    _require_internal_canary_token,
    _validate_translated_catalog,
    canary_source_catalog,
    canonical_source_catalog,
    requested_source_catalog,
)
from app.core.config import settings
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


def test_exact_canonical_subset_is_accepted_for_fast_core_hydration():
    source = canonical_source_catalog()
    core = {key: source[key] for key in ("language", "settings", "save", "support")}
    assert requested_source_catalog(core) == core


def test_commercial_boundary_source_is_canonical_and_accepts_exact_subset():
    canonical = canonical_source_catalog()
    subset = {
        "commercialBoundary.title.upgrade": "Upgrade to continue",
        "commercialBoundary.body.unavailable": "This capability is not included in the organization’s current commercial state.",
        "commercialBoundary.upgradeTo": "Upgrade to {plan}",
    }
    assert all(canonical[key] == value for key, value in subset.items())
    assert requested_source_catalog(subset) == subset


def test_commercial_boundary_subset_value_drift_is_rejected():
    with pytest.raises(ValueError, match="ui_source_catalog_mismatch"):
        requested_source_catalog({"commercialBoundary.title.upgrade": "Changed outside canonical source"})


def test_commercial_boundary_placeholder_contract_is_canonical():
    canonical = canonical_source_catalog()
    assert canonical["commercialBoundary.upgradeTo"] == "Upgrade to {plan}"
    assert canonical["commercialBoundary.reasonFeatureMetric"].count("{feature}") == 1
    assert canonical["commercialBoundary.reasonFeatureMetric"].count("{metric}") == 1


def test_subset_with_value_drift_is_rejected():
    with pytest.raises(ValueError, match="ui_source_catalog_mismatch"):
        requested_source_catalog({"language": "Wrong value"})


def test_subset_with_unknown_key_is_rejected():
    with pytest.raises(ValueError, match="ui_source_catalog_mismatch"):
        requested_source_catalog({"not.a.real.key": "Nope"})


def test_canary_source_is_small_canonical_ui_subset():
    source = canary_source_catalog()
    assert source == {
        "language": "Language",
        "settings": "Settings",
        "save": "Save",
        "support": "Support",
    }
    assert requested_source_catalog(source) == source


def test_canary_locale_canonicalization_uses_enabled_registry():
    assert _canonical_enabled_locale("de") == "de"
    assert _canonical_enabled_locale("fr_fr") == "fr-FR"
    with pytest.raises(HTTPException) as exc:
        _canonical_enabled_locale("made-up-locale")
    assert exc.value.status_code == 422


def test_internal_canary_token_is_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "matrix-secret")
    _require_internal_canary_token("Bearer matrix-secret")
    for supplied in (None, "", "Bearer wrong", "Basic matrix-secret"):
        with pytest.raises(HTTPException) as exc:
            _require_internal_canary_token(supplied)
        assert exc.value.status_code == 401


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

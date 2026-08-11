from __future__ import annotations

import pytest

from app.api.v1 import i18n as i18n_module
from app.services.i18n_translation_resilience import normalize_singleton_key_drift


def test_singleton_translated_key_is_restored_when_value_mapping_is_unambiguous():
    source = {"language": "Language"}
    assert normalize_singleton_key_drift(source, {"언어": "언어"}) == {"language": "언어"}
    assert i18n_module._validate_translated_catalog(source, {"언어": "언어"}) == {"language": "언어"}


def test_multi_key_drift_remains_fail_closed():
    source = {"language": "Language", "save": "Save"}
    translated = {"언어": "언어", "저장": "저장"}
    assert normalize_singleton_key_drift(source, translated) == translated
    with pytest.raises(ValueError, match="keys do not match"):
        i18n_module._validate_translated_catalog(source, translated)


def test_singleton_repair_does_not_relax_value_or_placeholder_validation():
    with pytest.raises(ValueError, match="invalid translated value"):
        i18n_module._validate_translated_catalog({"language": "Language"}, {"언어": ""})
    with pytest.raises(ValueError, match="placeholders"):
        i18n_module._validate_translated_catalog(
            {"upgrade": "Upgrade to {plan}"},
            {"업그레이드": "업그레이드"},
        )

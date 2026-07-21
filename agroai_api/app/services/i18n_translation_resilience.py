"""Narrow resilience repair for model-generated UI catalogs.

Some translation models correctly translate a singleton value but translate the
JSON key as well (for example ``{"언어": "언어"}`` for the canonical key
``language``). The i18n pipeline already recursively splits failed chunks down
to a single key. At that final boundary the value association is unambiguous,
so restoring the sole canonical key is safe; multi-key key drift remains
strictly rejected.
"""
from __future__ import annotations

from typing import Any

_INSTALLED = False


def normalize_singleton_key_drift(source: dict[str, str], translated: Any) -> Any:
    """Restore one unambiguous canonical key without relaxing larger catalogs."""
    if not isinstance(translated, dict):
        return translated
    if len(source) != 1 or len(translated) != 1 or set(source) == set(translated):
        return translated
    canonical_key = next(iter(source))
    translated_value = next(iter(translated.values()))
    return {canonical_key: translated_value}


def install_i18n_translation_resilience(i18n_module: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(i18n_module, "_singleton_key_resilience_installed", False):
        return

    original_validate = i18n_module._validate_translated_catalog

    def validate_with_singleton_repair(source: dict[str, str], translated: Any) -> dict[str, str]:
        return original_validate(source, normalize_singleton_key_drift(source, translated))

    i18n_module._validate_translated_catalog = validate_with_singleton_repair
    i18n_module._singleton_key_resilience_installed = True
    _INSTALLED = True

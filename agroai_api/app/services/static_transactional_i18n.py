from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from app.services.language_registry import canonical_ui_locale

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_PATH = _REPO_ROOT / "shared" / "localization" / "transactional-source.json"
_CATALOG_DIR = _REPO_ROOT / "shared" / "localization" / "transactional-catalogs"


def _fingerprint(catalog: dict[str, str]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1)
def _source_envelope() -> dict:
    return json.loads(_SOURCE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=128)
def _catalog(locale: str) -> dict[str, str] | None:
    path = _CATALOG_DIR / f"{locale}.json"
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    source_envelope = _source_envelope()
    source = source_envelope.get("catalog") or {}
    if (
        envelope.get("schemaVersion") != 1
        or envelope.get("locale") != locale
        or envelope.get("status") != "complete-generated"
        or envelope.get("sourceVersion") != source_envelope.get("version")
        or envelope.get("sourceFingerprint") != _fingerprint(source)
    ):
        return None
    catalog = envelope.get("catalog")
    if not isinstance(catalog, dict) or set(catalog) != set(source):
        return None
    if any(not isinstance(value, str) or not value.strip() for value in catalog.values()):
        return None
    return {str(key): str(value) for key, value in catalog.items()}


def localize_static_transactional_strings(locale: str | None, source: dict[str, str]) -> dict[str, str] | None:
    try:
        canonical = canonical_ui_locale(locale or "en")
    except ValueError:
        canonical = "en"
    if canonical == "auto":
        canonical = "en"
    if canonical == "en":
        return dict(source)
    if canonical == "pt":
        canonical = "pt-BR"

    translated = _catalog(canonical)
    if not translated:
        return None

    english = _source_envelope().get("catalog") or {}
    keys_by_value: dict[str, list[str]] = {}
    for key, value in english.items():
        if isinstance(value, str):
            keys_by_value.setdefault(value, []).append(str(key))

    localized: dict[str, str] = {}
    for field, value in source.items():
        candidates = keys_by_value.get(value) or []
        translated_value = next((translated.get(key) for key in candidates if translated.get(key)), None)
        if not isinstance(translated_value, str) or not translated_value.strip():
            return None
        localized[field] = translated_value.strip()
    return localized

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = _REPO_ROOT / "shared" / "supported-locales.json"
_AI_TARGETS_PATH = _REPO_ROOT / "shared" / "chatgpt-language-targets.json"

RTL_LANGUAGE_FAMILIES = {"ar", "fa", "he", "ps", "sd", "ur", "ug", "yi", "ckb"}


@dataclass(frozen=True)
class LanguageFamily:
    code: str
    name: str
    direction: str = "ltr"


@dataclass(frozen=True)
class LocaleSpec:
    code: str
    language_code: str
    direction: str
    fallback_chain: tuple[str, ...]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def manifest() -> dict:
    return _load_json(_MANIFEST_PATH)


@lru_cache(maxsize=1)
def ai_targets() -> dict:
    return _load_json(_AI_TARGETS_PATH)


@lru_cache(maxsize=1)
def language_families() -> dict[str, LanguageFamily]:
    families: dict[str, LanguageFamily] = {
        "auto": LanguageFamily("auto", "User message language", "ltr"),
        "en": LanguageFamily("en", "English", "ltr"),
    }
    for item in ai_targets().get("families", []):
        code = str(item.get("code") or "").strip().lower()
        name = str(item.get("name") or code).strip()
        if code:
            families[code] = LanguageFamily(
                code=code,
                name=name,
                direction="rtl" if code in RTL_LANGUAGE_FAMILIES else "ltr",
            )
    for item in manifest().get("locales", []):
        code = str(item.get("languageCode") or "").strip().lower()
        if code and code not in families:
            families[code] = LanguageFamily(
                code=code,
                name=code,
                direction=str(item.get("direction") or ("rtl" if code in RTL_LANGUAGE_FAMILIES else "ltr")),
            )
    return families


@lru_cache(maxsize=1)
def locale_specs() -> dict[str, LocaleSpec]:
    specs: dict[str, LocaleSpec] = {}
    for item in manifest().get("locales", []):
        code = str(item.get("code") or "").strip()
        language_code = str(item.get("languageCode") or code).strip().lower()
        if not code:
            continue
        specs[code.lower()] = LocaleSpec(
            code=code,
            language_code=language_code,
            direction=str(item.get("direction") or ("rtl" if language_code in RTL_LANGUAGE_FAMILIES else "ltr")),
            fallback_chain=tuple(str(value) for value in item.get("fallbackChain", []) if value),
        )
    return specs


def normalize_bcp47(value: str | None) -> str:
    raw = (value or "auto").strip().replace("_", "-")
    if not raw:
        return "auto"
    parts = raw.split("-")
    language = parts[0].lower()
    if language == "auto":
        return "auto"
    normalized = [language]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        else:
            normalized.append(part)
    return "-".join(normalized)


def language_root(value: str | None) -> str:
    return normalize_bcp47(value).split("-", 1)[0].lower()


def family_supported(code: str | None) -> bool:
    return language_root(code) in language_families()


def family_name(code: str | None) -> str:
    root = language_root(code)
    family = language_families().get(root)
    return family.name if family else root


def family_direction(code: str | None) -> str:
    root = language_root(code)
    family = language_families().get(root)
    if family:
        return family.direction
    return "rtl" if root in RTL_LANGUAGE_FAMILIES else "ltr"


def enabled_ui_locales() -> tuple[str, ...]:
    return tuple(str(code) for code in manifest().get("enabledUiLocales", []))


def catalog_complete_locales() -> tuple[str, ...]:
    return tuple(str(code) for code in manifest().get("catalogCompleteLocales", []))


def all_ai_response_families() -> tuple[str, ...]:
    return tuple(sorted(code for code in language_families() if code != "auto"))

#!/usr/bin/env python3
"""Shared release-quality rules for deterministic UI locale catalogs.

Used by both the build-time generator and the production readiness reconciler so
that "ready to advertise" has exactly one definition.
"""
from __future__ import annotations

import re
import unicodedata

TOKENS = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
# Residue of authoring-time protection markers must never reach customers.
MARKER_RESIDUE = re.compile(r"AGROAI[_ ]?(?:KEEP|ITEM)|<<<|>>>", re.I)


def has_marker_residue(value: str) -> bool:
    return bool(MARKER_RESIDUE.search(value))

# Copy-pasteable code and wire-protocol literals must stay byte-identical in
# every locale (e.g. curl examples, HTTP verbs + paths, JSON request bodies).
_DO_NOT_TRANSLATE = re.compile(
    r"^\s*(?:curl\s|-H\s|-d\s|(?:GET|POST|PUT|PATCH|DELETE)\s+/|\{\s*\")"
    r"|\$[A-Z][A-Z0-9_]{2,}"
    r"|^Bearer\s*/\s*X-API-Key$"
)

# Scripts whose customer-visible text must be predominantly non-Latin.
NATIVE_SCRIPT = {
    "ar": "ARABIC", "fa": "ARABIC", "ur": "ARABIC",
    "ru": "CYRILLIC", "uk": "CYRILLIC", "bg": "CYRILLIC", "mk": "CYRILLIC",
    "sr": "CYRILLIC", "kk": "CYRILLIC", "mn": "CYRILLIC",
    "el": "GREEK", "hy": "ARMENIAN", "ka": "GEORGIAN",
    "hi": "DEVANAGARI", "mr": "DEVANAGARI", "bn": "BENGALI", "gu": "GUJARATI",
    "pa": "GURMUKHI", "ta": "TAMIL", "te": "TELUGU", "kn": "KANNADA",
    "ml": "MALAYALAM", "th": "THAI", "my": "MYANMAR", "am": "ETHIOPIC",
    "ja": "CJK|HIRAGANA|KATAKANA", "zh": "CJK", "ko": "HANGUL",
}

# Release thresholds, measured over translatable strings only.
MAX_IDENTICAL_TO_ENGLISH = 0.05
MIN_NATIVE_SCRIPT_SHARE = 0.90


def do_not_translate(value: str) -> bool:
    return bool(_DO_NOT_TRANSLATE.search(value))


def translatable(value: str) -> bool:
    """Prose that a customer would expect to read in their language."""
    return not do_not_translate(value) and len(re.findall(r"[A-Za-z]{3,}", value)) >= 2


def _native_share(value: str, script: str) -> float:
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return 1.0
    hits = sum(1 for ch in letters if re.search(script, unicodedata.name(ch, "")))
    return hits / len(letters)


def english_leak_keys(locale: str, source: dict[str, str], catalog: dict[str, str]) -> list[str]:
    """Keys whose translation is still (substantively) English."""
    root = locale.split("-", 1)[0].lower()
    script = NATIVE_SCRIPT.get(root)
    leaks: list[str] = []
    for key, original in source.items():
        if not translatable(original):
            continue
        value = catalog.get(key, "")
        if value.strip() == original.strip():
            leaks.append(key)
        elif script and _native_share(value, script) < 0.5:
            leaks.append(key)
    return leaks


def quality_report(locale: str, source: dict[str, str], catalog: dict[str, str]) -> dict:
    root = locale.split("-", 1)[0].lower()
    prose = [key for key, value in source.items() if translatable(value)]
    identical = sum(1 for key in prose if catalog.get(key, "").strip() == source[key].strip())
    report = {
        "locale": locale,
        "translatable": len(prose),
        "identicalToEnglish": identical,
        "identicalShare": round(identical / max(1, len(prose)), 4),
        "dntViolations": [key for key, value in source.items() if do_not_translate(value) and catalog.get(key) != value],
    }
    script = NATIVE_SCRIPT.get(root)
    if script:
        low = sum(1 for key in prose if _native_share(catalog.get(key, ""), script) < 0.5)
        report["nativeScriptShare"] = round(1 - low / max(1, len(prose)), 4)
    return report


def quality_errors(locale: str, source: dict[str, str], catalog: dict[str, str]) -> list[str]:
    if locale == "en":
        return []
    report = quality_report(locale, source, catalog)
    errors: list[str] = []
    residue = [key for key, value in catalog.items() if has_marker_residue(value) and not has_marker_residue(source.get(key, ""))]
    if residue:
        errors.append(f"authoring_marker_residue:{locale}:{','.join(residue[:5])}")
    if report["dntViolations"]:
        errors.append(f"do_not_translate_modified:{locale}:{','.join(report['dntViolations'][:5])}")
    if report["identicalShare"] > MAX_IDENTICAL_TO_ENGLISH:
        errors.append(f"english_leakage:{locale}:{report['identicalShare']:.3f}>{MAX_IDENTICAL_TO_ENGLISH}")
    if "nativeScriptShare" in report and report["nativeScriptShare"] < MIN_NATIVE_SCRIPT_SHARE:
        errors.append(f"native_script_share:{locale}:{report['nativeScriptShare']:.3f}<{MIN_NATIVE_SCRIPT_SHARE}")
    return errors

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


# A bracket glued to a placeholder ("{price}>", "<{plan}") is left over from a
# widened protection marker, not translation.
PLACEHOLDER_BRACKET = re.compile(r"\}[>＞》〉]|[<＜《〈]\{")


def has_placeholder_bracket_residue(value: str, source: str) -> bool:
    return bool(PLACEHOLDER_BRACKET.search(value)) and not PLACEHOLDER_BRACKET.search(source)

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


_PRESERVED_TOKEN = re.compile(r"\b(?:[A-Z][A-Za-z0-9.+&/-]*|[A-Za-z]*\d[A-Za-z0-9.-]*)\b")


def _native_share(value: str, script: str) -> float:
    # Proper nouns, product names, acronyms and unit/identifier tokens are
    # correctly preserved in Latin script; untranslated English prose is
    # dominated by lowercase words and is still measured.
    value = _PRESERVED_TOKEN.sub(" ", value)
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return 1.0
    hits = sum(1 for ch in letters if re.search(script, unicodedata.name(ch, "")))
    return hits / len(letters)


def _script_of(ch: str) -> str:
    name = unicodedata.name(ch, "")
    if not name or not ch.isalpha():
        return ""
    if name.startswith("LATIN") or name.startswith("FULLWIDTH LATIN"):
        return "LATIN"
    for script in ("ARABIC", "CYRILLIC", "GREEK", "ARMENIAN", "GEORGIAN", "DEVANAGARI", "BENGALI", "GUJARATI",
                   "GURMUKHI", "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "THAI", "MYANMAR", "ETHIOPIC",
                   "HANGUL", "HIRAGANA", "KATAKANA", "CJK", "HEBREW", "SINHALA", "KHMER", "LAO", "TIBETAN"):
        if name.startswith(script) or f" {script} " in f" {name} ":
            return script
    return "OTHER"


def foreign_script(locale: str, value: str) -> bool:
    """Letters from a script the locale never uses (e.g. Devanagari in Amharic)."""
    root = locale.split("-", 1)[0].lower()
    allowed = {"LATIN", ""}
    allowed.update((NATIVE_SCRIPT.get(root) or "").split("|"))
    if root == "ja":
        allowed.update({"CJK", "HIRAGANA", "KATAKANA"})
    return any(_script_of(ch) not in allowed for ch in value)


def english_leak_keys(locale: str, source: dict[str, str], catalog: dict[str, str]) -> list[str]:
    """Keys whose translation is still (substantively) English."""
    root = locale.split("-", 1)[0].lower()
    script = NATIVE_SCRIPT.get(root)
    leaks: list[str] = []
    for key, original in source.items():
        if not translatable(original):
            continue
        value = catalog.get(key, "")
        if foreign_script(locale, value) and not foreign_script(locale, original):
            leaks.append(key)
        elif value.strip() == original.strip():
            leaks.append(key)
        elif script and _native_share(value, script) < 0.5:
            leaks.append(key)
    return leaks


# Degenerate provider output: a model that cannot translate a language loops on
# one token ("mid ka mid ah mid ka mid ah ...") or balloons a short string. Such
# entries pass key/placeholder/script checks, so they are rejected explicitly.
_REPEATED_RUN = re.compile(r"(\b\w+(?:\s+\w+){0,3}\b)(?:[\s,.:;»«]+\1\b){4,}", re.I | re.U)
_LENGTH_BLOWUP = 4.0


def degenerate(value: str, original: str) -> bool:
    if not isinstance(value, str):
        return False
    if _REPEATED_RUN.search(value) and not _REPEATED_RUN.search(original or ""):
        return True
    return len(original or "") > 20 and len(value) > _LENGTH_BLOWUP * len(original)


def degenerate_keys(source: dict[str, str], catalog: dict[str, str]) -> list[str]:
    return [key for key, original in source.items() if degenerate(catalog.get(key, ""), original)]


def collapsed_values(source: dict[str, str], catalog: dict[str, str]) -> dict[str, int]:
    """Translations reused for implausibly many distinct English strings.

    A provider that does not know the language returns one stock phrase for
    unrelated inputs ("Lees meer »" for Settings, Billing and Password). Healthy
    catalogs reuse a value for at most a handful of distinct source strings.
    """
    limit = max(4, int(len(source) * 0.004))
    sources_by_value: dict[str, set[str]] = {}
    for key, original in source.items():
        value = catalog.get(key)
        if isinstance(value, str) and isinstance(original, str) and len(value.strip()) >= 2:
            sources_by_value.setdefault(value.strip(), set()).add(original.strip().lower())
    return {value: len(origins) for value, origins in sources_by_value.items() if len(origins) > limit}


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
    contaminated = [key for key, value in catalog.items() if foreign_script(locale, value) and not foreign_script(locale, source.get(key, ""))]
    if contaminated:
        errors.append(f"foreign_script:{locale}:{','.join(contaminated[:5])}")
    residue = [key for key, value in catalog.items() if has_marker_residue(value) and not has_marker_residue(source.get(key, ""))]
    if residue:
        errors.append(f"authoring_marker_residue:{locale}:{','.join(residue[:5])}")
    bracketed = [key for key, value in catalog.items() if has_placeholder_bracket_residue(value, source.get(key, ""))]
    if bracketed:
        errors.append(f"placeholder_bracket_residue:{locale}:{','.join(bracketed[:5])}")
    collapsed = collapsed_values(source, catalog)
    if collapsed:
        errors.append(f"collapsed_output:{locale}:{len(collapsed)}")
    looping = degenerate_keys(source, catalog)
    if looping:
        errors.append(f"degenerate_output:{locale}:{len(looping)}:{','.join(looping[:5])}")
    if report["dntViolations"]:
        errors.append(f"do_not_translate_modified:{locale}:{','.join(report['dntViolations'][:5])}")
    if report["identicalShare"] > MAX_IDENTICAL_TO_ENGLISH:
        errors.append(f"english_leakage:{locale}:{report['identicalShare']:.3f}>{MAX_IDENTICAL_TO_ENGLISH}")
    if "nativeScriptShare" in report and report["nativeScriptShare"] < MIN_NATIVE_SCRIPT_SHARE:
        errors.append(f"native_script_share:{locale}:{report['nativeScriptShare']:.3f}<{MIN_NATIVE_SCRIPT_SHARE}")
    return errors


# Serbian is digraphic. AGRO-AI presents Serbian in Cyrillic ("Српски"); some
# provider outputs come back in Serbian Latin, so normalize deterministically.
_SR_DIGRAPHS = {"Lj": "Љ", "LJ": "Љ", "lj": "љ", "Nj": "Њ", "NJ": "Њ", "nj": "њ", "Dž": "Џ", "DŽ": "Џ", "dž": "џ"}
_SR_LETTERS = dict(zip(
    "ABCČĆDĐEFGHIJKLMNOPRSŠTUVZŽabcčćdđefghijklmnoprsštuvzž",
    "АБЦЧЋДЂЕФГХИЈКЛМНОПРСШТУВЗЖабцчћдђефгхијклмнопрсштувзж",
))
_WORD = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}|https?://\S+|[\w\u00C0-\u024F'’-]+")


def serbian_latin_to_cyrillic(value: str, english_source: str) -> str:
    """Transliterate Serbian-Latin words; keep tokens copied from the English source."""
    keep = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9.+&/_-]*", english_source))
    keep |= {token.rstrip(".") for token in keep}  # "Inc." in the source keeps "Inc"

    def convert(match: re.Match) -> str:
        word = match.group(0)
        if word.startswith("{") or word.startswith("http") or word in keep or not re.search(r"[A-Za-zČĆĐŠŽčćđšž]", word):
            return word
        if re.search(r"[A-Z]{2,}|\d", word):  # acronyms / identifiers
            return word
        out, index = [], 0
        while index < len(word):
            pair = word[index:index + 2]
            if pair in _SR_DIGRAPHS:
                out.append(_SR_DIGRAPHS[pair]); index += 2
                continue
            out.append(_SR_LETTERS.get(word[index], word[index])); index += 1
        return "".join(out)

    return _WORD.sub(convert, value)


def serbian_script_keys(locale: str, source: dict[str, str], catalog: dict[str, str]) -> list[str]:
    """AGRO-AI presents Serbian in Cyrillic; values still in Serbian Latin are not ready."""
    if locale.split("-", 1)[0].lower() != "sr":
        return []
    return [key for key, original in source.items()
            if isinstance(catalog.get(key), str) and serbian_latin_to_cyrillic(catalog[key], original) != catalog[key]]

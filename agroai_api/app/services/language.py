from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.language_registry import (
    family_direction,
    family_name,
    family_supported,
    language_families,
    language_root,
)


_NATIVE_ALIASES = {
    "english": "en", "anglais": "en", "inglés": "en", "ingles": "en",
    "french": "fr", "français": "fr", "francais": "fr", "francés": "fr",
    "spanish": "es", "español": "es", "espanol": "es", "espagnol": "es",
    "portuguese": "pt", "português": "pt", "portugues": "pt", "portugais": "pt",
    "arabic": "ar", "العربية": "ar", "arabe": "ar",
    "german": "de", "deutsch": "de", "allemand": "de",
    "italian": "it", "italiano": "it", "italien": "it",
    "dutch": "nl", "nederlands": "nl",
    "turkish": "tr", "türkçe": "tr", "turkce": "tr",
    "chinese": "zh", "中文": "zh", "汉语": "zh", "漢語": "zh",
    "japanese": "ja", "日本語": "ja",
    "korean": "ko", "한국어": "ko",
    "russian": "ru", "русский": "ru",
    "swahili": "sw", "kiswahili": "sw",
    "hindi": "hi", "हिन्दी": "hi", "हिंदी": "hi",
    "bengali": "bn", "বাংলা": "bn",
    "persian": "fa", "فارسی": "fa", "farsi": "fa",
    "urdu": "ur", "اردو": "ur",
    "ukrainian": "uk", "українська": "uk",
    "polish": "pl", "polski": "pl",
    "somali": "so", "soomaali": "so",
}


def _language_aliases() -> dict[str, str]:
    aliases = dict(_NATIVE_ALIASES)
    for code, family in language_families().items():
        if code == "auto":
            continue
        aliases.setdefault(code.lower(), code)
        aliases.setdefault(family.name.lower(), code)
    return aliases


_LANGUAGE_ALIASES = _language_aliases()

_TOKEN_HINTS: dict[str, tuple[str, ...]] = {
    "en": (
        " the ", " and ", " with ", " what ", " why ", " how ", " can you ",
        " do you ", " should ", " would ", " please ", " help me ", " my data ",
        " access ", " analyse ", " analyze ", " water ", " field ",
    ),
    "fr": (
        " le ", " la ", " les ", " des ", " avec ", " pour ", " est-ce ",
        " est ce ", " peux-tu ", " tu peux ", " pouvez ", " combien ", " dois-je ",
        " données ", " donnees ", " eau ", " aider ", " pourquoi ", " comment ",
    ),
    "es": (
        " el ", " la ", " los ", " las ", " con ", " para ", " puedes ",
        " puede ", " cuánto ", " cuanto ", " agua ", " datos ", " ayudar ",
        " por qué ", " porque ", " cómo ", " como ",
    ),
    "pt": (
        " o ", " a ", " os ", " as ", " com ", " para ", " você ", " voce ",
        " quanto ", " água ", " agua ", " dados ", " ajudar ", " por que ",
        " como ", " irrigação ", " irrigacao ",
    ),
    "de": (" der ", " die ", " das ", " und ", " mit ", " für ", " fuer ", " wie ", " warum ", " wasser ", " daten "),
    "it": (" il ", " lo ", " la ", " gli ", " le ", " con ", " per ", " come ", " perché ", " perche ", " acqua ", " dati "),
    "nl": (" de ", " het ", " een ", " en ", " met ", " voor ", " hoe ", " waarom ", " water ", " gegevens "),
    "tr": (" ve ", " ile ", " için ", " icin ", " nasıl ", " nasil ", " neden ", " su ", " veri "),
    "sw": (" na ", " kwa ", " jinsi ", " kwa nini ", " maji ", " data ", " shamba "),
    "so": (" iyo ", " waa ", " maxay ", " sidee ", " biyo ", " beer ", " xog "),
    "id": (" dan ", " dengan ", " untuk ", " bagaimana ", " mengapa ", " air ", " data "),
    "vi": (" và ", " với ", " cho ", " như thế nào ", " tại sao ", " nước ", " dữ liệu "),
}

_REQUEST_MARKERS = (
    "answer in ", "reply in ", "respond in ", "write in ", "speak in ",
    "réponds en ", "reponds en ", "répondez en ", "repondez en ",
    "contesta en ", "responde en ", "escribe en ",
    "responda em ", "escreva em ",
    "antworte auf ", "schreibe auf ",
    "rispondi in ", "scrivi in ",
    "ответь на ", "ответьте на ",
    "اكتب ب", "أجب ب", "اجب ب",
)


@dataclass(frozen=True)
class LanguageDecision:
    selected_code: str
    selected_name: str
    detected_code: str | None
    detected_name: str | None
    response_code: str
    response_name: str
    direction: str
    instruction: str
    explicit_code: str | None = None


def normalize_locale(value: str | None) -> str:
    root = language_root(value)
    if root == "auto":
        return "auto"
    return root if family_supported(root) else root


def language_name(code: str | None) -> str:
    return family_name(code)


def direction_for(code: str | None) -> str:
    return family_direction(code)


def detect_explicit_language_request(text: str | None) -> str | None:
    value = (text or "").strip().lower()
    if not value:
        return None
    for marker in _REQUEST_MARKERS:
        if marker not in value:
            continue
        tail = value.split(marker, 1)[1][:80]
        for alias, code in sorted(_LANGUAGE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if alias and alias in tail:
                return code
    return None


def _script_language(value: str) -> tuple[str | None, str | None]:
    # Unambiguous scripts can make a deterministic family decision. Shared
    # scripts remain hints only; the model receives an explicit same-language
    # instruction in auto mode rather than being forced to English.
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja", "Japanese kana"
    if re.search(r"[\uac00-\ud7af]", value):
        return "ko", "Korean Hangul"
    if re.search(r"[\u4e00-\u9fff]", value):
        return "zh", "Han script"
    if re.search(r"[\u0590-\u05ff]", value):
        return None, "Hebrew-family script"
    if re.search(r"[\u0600-\u06ff]", value):
        return None, "Arabic-family script"
    if re.search(r"[\u0400-\u04ff]", value):
        return None, "Cyrillic script"
    if re.search(r"[\u0980-\u09ff]", value):
        return "bn", "Bengali script"
    if re.search(r"[\u0a80-\u0aff]", value):
        return "gu", "Gujarati script"
    if re.search(r"[\u0a00-\u0a7f]", value):
        return "pa", "Gurmukhi script"
    if re.search(r"[\u0b80-\u0bff]", value):
        return "ta", "Tamil script"
    if re.search(r"[\u0c00-\u0c7f]", value):
        return "te", "Telugu script"
    if re.search(r"[\u0c80-\u0cff]", value):
        return "kn", "Kannada script"
    if re.search(r"[\u0d00-\u0d7f]", value):
        return "ml", "Malayalam script"
    if re.search(r"[\u0e00-\u0e7f]", value):
        return "th", "Thai script"
    if re.search(r"[\u10a0-\u10ff]", value):
        return "ka", "Georgian script"
    if re.search(r"[\u0530-\u058f]", value):
        return "hy", "Armenian script"
    if re.search(r"[\u0370-\u03ff]", value):
        return "el", "Greek script"
    if re.search(r"[\u0900-\u097f]", value):
        return None, "Devanagari script"
    return None, None


def detect_language_hint(text: str | None) -> tuple[str | None, str | None]:
    value = text or ""
    script_code, script_label = _script_language(value)
    if script_code:
        return script_code, script_label

    normalized = " " + re.sub(r"\s+", " ", value.lower().replace("’", "'")) + " "
    scores = {code: sum(1 for token in tokens if token in normalized) for code, tokens in _TOKEN_HINTS.items()}
    if not scores:
        return None, script_label
    best_code, best_score = max(scores.items(), key=lambda item: item[1])
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    if best_score >= 2 and best_score > second:
        return best_code, f"{language_name(best_code)} lexical hint"
    if best_score >= 3:
        return best_code, f"{language_name(best_code)} lexical hint"
    return None, script_label


def resolve_language(selected: str | None, user_text: str | None) -> LanguageDecision:
    selected_code = normalize_locale(selected)
    explicit_code = detect_explicit_language_request(user_text)
    detected_code, detected_label = detect_language_hint(user_text)
    response_code = explicit_code or detected_code or (selected_code if selected_code != "auto" else "auto")

    selected_name = language_name(selected_code)
    detected_name = language_name(detected_code) if detected_code else None
    response_name = language_name(response_code)

    if response_code == "auto":
        instruction = (
            "MANDATORY RESPONSE LANGUAGE: answer in the same natural language as the user's current message. "
            "Do not default to English merely because agriculture, telemetry, API, model, controller, ET, or compliance terms are English. "
            "For mixed-language input, follow the dominant conversational language while preserving proper nouns and exact technical tokens. "
            "If the language is genuinely indeterminate, avoid inventing a language preference and ask only the minimum clarification needed. "
            "The language rule constrains only language, not substance or structure. Preserve exact numbers, units, citations, uncertainty, negative instructions, and operational meaning."
        )
    else:
        instruction = (
            f"MANDATORY RESPONSE LANGUAGE: {response_name} ({response_code}). "
            f"Selected portal language: {selected_name} ({selected_code}). "
            f"Detected current-message language: {detected_name or 'not confidently detected'}"
            f"{f' - {detected_label}' if detected_label else ''}. "
            f"You must answer in {response_name}. The language rule constrains only the language, not the substance or structure of the answer. "
            "Answer the user's exact question naturally and adapt depth to the request. "
            "Do not explain the language choice. Preserve precise agriculture, irrigation, ET, controller, telemetry, compliance, and water-accounting terms."
        )

    return LanguageDecision(
        selected_code=selected_code,
        selected_name=selected_name,
        detected_code=detected_code,
        detected_name=detected_name,
        response_code=response_code,
        response_name=response_name,
        direction=direction_for(response_code if response_code != "auto" else selected_code),
        instruction=instruction,
        explicit_code=explicit_code,
    )


def language_matches_target(text: str, target_code: str) -> bool:
    target = normalize_locale(target_code)
    if target == "auto":
        return True
    detected, _ = detect_language_hint(text)
    if detected:
        return detected == target
    if target == "en":
        return looks_english(text)
    return True


def looks_english(text: str) -> bool:
    value = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    hits = sum(
        1
        for token in (
            " the ", " and ", " with ", " what ", " why ", " how ", " can ",
            " should ", " would ", " workspace ", " evidence ", " field ",
            " report ", " water ", " data ", " next ", " access ",
        )
        if token in value
    )
    return hits >= 2

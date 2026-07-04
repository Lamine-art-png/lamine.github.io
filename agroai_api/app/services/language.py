from __future__ import annotations

import re
from dataclasses import dataclass


RTL_LANGUAGES = {"ar", "he", "fa", "ur", "ps", "sd", "ckb", "ug", "yi"}

LANGUAGE_NAMES: dict[str, str] = {
    "auto": "Auto / user's detected language",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "ar": "Arabic",
    "zh": "Chinese",
    "hi": "Hindi",
    "bn": "Bengali",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "it": "Italian",
    "tr": "Turkish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "sw": "Swahili",
    "wo": "Wolof",
    "ff": "Fulfulde",
    "ha": "Hausa",
    "yo": "Yoruba",
    "ig": "Igbo",
    "am": "Amharic",
    "fa": "Persian",
    "ur": "Urdu",
    "pl": "Polish",
    "nl": "Dutch",
    "uk": "Ukrainian",
    "ro": "Romanian",
    "el": "Greek",
    "he": "Hebrew",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "pa": "Punjabi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
}

_LANGUAGE_ALIASES = {
    "english": "en", "anglais": "en", "inglés": "en", "ingles": "en",
    "french": "fr", "français": "fr", "francais": "fr", "francés": "fr",
    "spanish": "es", "español": "es", "espanol": "es", "espagnol": "es", "espagnole": "es",
    "portuguese": "pt", "português": "pt", "portugues": "pt", "portugais": "pt",
    "arabic": "ar", "arabe": "ar",
    "german": "de", "deutsch": "de", "allemand": "de",
    "italian": "it", "italiano": "it", "italien": "it",
    "dutch": "nl", "nederlands": "nl",
    "turkish": "tr", "türkçe": "tr", "turkce": "tr",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "russian": "ru", "русский": "ru",
    "swahili": "sw", "kiswahili": "sw",
    "wolof": "wo",
}

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
    "wo": (" ak ", " ci ", " ndax ", " naka ", " ndox ", " tool "),
}


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
    raw = (value or "auto").strip().lower().replace("_", "-")
    if not raw:
        return "auto"
    return raw.split("-")[0] or "auto"


def language_name(code: str | None) -> str:
    root = normalize_locale(code)
    return LANGUAGE_NAMES.get(root, root)


def direction_for(code: str | None) -> str:
    return "rtl" if normalize_locale(code) in RTL_LANGUAGES else "ltr"


def detect_explicit_language_request(text: str | None) -> str | None:
    value = (text or "").strip().lower()
    if not value:
        return None
    request_markers = (
        "answer in ", "reply in ", "respond in ", "write in ", "speak in ",
        "réponds en ", "reponds en ", "répondez en ", "repondez en ",
        "contesta en ", "responde en ", "escribe en ",
        "responda em ", "escreva em ",
    )
    for marker in request_markers:
        if marker in value:
            tail = value.split(marker, 1)[1][:48]
            for alias, code in _LANGUAGE_ALIASES.items():
                if alias in tail:
                    return code
    return None


def _script_language(value: str) -> tuple[str | None, str | None]:
    # Ambiguous writing systems are diagnostic hints, not language decisions.
    if re.search(r"[\u0600-\u06ff]", value):
        return None, "Arabic-family script"
    if re.search(r"[\u0590-\u05ff]", value):
        return "he", "Hebrew script"
    if re.search(r"[\u0400-\u04ff]", value):
        return None, "Cyrillic script"
    if re.search(r"[\u4e00-\u9fff]", value):
        return "zh", "Chinese script"
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja", "Japanese script"
    if re.search(r"[\uac00-\ud7af]", value):
        return "ko", "Korean script"
    if re.search(r"[\u0980-\u09ff]", value):
        return "bn", "Bengali script"
    if re.search(r"[\u0900-\u097f]", value):
        return None, "Devanagari script"
    if re.search(r"[\u0b80-\u0bff]", value):
        return "ta", "Tamil script"
    if re.search(r"[\u0c00-\u0c7f]", value):
        return "te", "Telugu script"
    if re.search(r"[\u0d00-\u0d7f]", value):
        return "ml", "Malayalam script"
    if re.search(r"[\u0e00-\u0e7f]", value):
        return "th", "Thai script"
    return None, None


def detect_language_hint(text: str | None) -> tuple[str | None, str | None]:
    value = text or ""
    script_code, script_label = _script_language(value)
    if script_code:
        return script_code, script_label

    normalized = " " + re.sub(r"\s+", " ", value.lower().replace("’", "'")) + " "
    scores: dict[str, int] = {}
    for code, tokens in _TOKEN_HINTS.items():
        scores[code] = sum(1 for token in tokens if token in normalized)

    if not scores:
        return None, script_label
    best_code, best_score = max(scores.items(), key=lambda item: item[1])
    sorted_scores = sorted(scores.values(), reverse=True)
    second = sorted_scores[1] if len(sorted_scores) > 1 else 0
    if best_score >= 2 and best_score > second:
        return best_code, f"{language_name(best_code)} lexical hint"
    if best_score >= 3:
        return best_code, f"{language_name(best_code)} lexical hint"
    return None, script_label


def resolve_language(selected: str | None, user_text: str | None) -> LanguageDecision:
    selected_code = normalize_locale(selected)
    explicit_code = detect_explicit_language_request(user_text)
    detected_code, detected_label = detect_language_hint(user_text)
    response_code = explicit_code or detected_code or (selected_code if selected_code != "auto" else "en")

    selected_name = language_name(selected_code)
    detected_name = language_name(detected_code) if detected_code else None
    response_name = language_name(response_code)
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
        direction=direction_for(response_code),
        instruction=instruction,
        explicit_code=explicit_code,
    )


def language_matches_target(text: str, target_code: str) -> bool:
    target = normalize_locale(target_code)
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

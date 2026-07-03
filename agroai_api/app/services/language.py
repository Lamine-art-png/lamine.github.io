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


def detect_language_hint(text: str | None) -> tuple[str | None, str | None]:
    value = text or ""
    if re.search(r"[\u0600-\u06ff]", value):
        return "ar", "Arabic/Persian/Urdu script"
    if re.search(r"[\u0590-\u05ff]", value):
        return "he", "Hebrew script"
    if re.search(r"[\u0400-\u04ff]", value):
        return "ru", "Cyrillic script"
    if re.search(r"[\u4e00-\u9fff]", value):
        return "zh", "Chinese script"
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja", "Japanese script"
    if re.search(r"[\uac00-\ud7af]", value):
        return "ko", "Korean script"
    if re.search(r"[\u0900-\u097f]", value):
        return "hi", "Indic script"
    lower = f" {value.lower()} "
    if any(token in lower for token in [" bonjour ", " merci ", " s'il ", " ferme ", " irrigation "]):
        return "fr", "French phrase hint"
    if any(token in lower for token in [" hola ", " gracias ", " campo ", " agua ", " riego "]):
        return "es", "Spanish phrase hint"
    if any(token in lower for token in [" olá ", " obrigado ", " obrigada ", " água ", " irrigação "]):
        return "pt", "Portuguese phrase hint"
    return None, None


def resolve_language(selected: str | None, user_text: str | None) -> LanguageDecision:
    selected_code = normalize_locale(selected)
    detected_code, detected_label = detect_language_hint(user_text)
    response_code = detected_code if selected_code == "auto" and detected_code else selected_code
    if response_code == "auto":
        response_code = "en"
    selected_name = language_name(selected_code)
    detected_name = language_name(detected_code) if detected_code else None
    response_name = language_name(response_code)
    instruction = (
        f"Selected portal language: {selected_name} ({selected_code}). "
        f"Detected user language hint: {detected_name or 'not detected'}"
        f"{f' - {detected_label}' if detected_label else ''}. "
        f"Answer in {response_name}. If the user explicitly asks for another language, follow the user's explicit request. "
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
    )

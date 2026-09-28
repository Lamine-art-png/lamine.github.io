from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from hashlib import sha256

from app.services.language_registry import canonical_ui_locale, family_name, locale_specs
from app.services.model_router import ModelRouter
from app.services.static_transactional_i18n import localize_static_transactional_strings

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_CACHE: dict[str, dict[str, str]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(locale: str, source: dict[str, str]) -> str:
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{locale}:{sha256(payload.encode('utf-8')).hexdigest()}"


def _decode_json_object(content: str) -> dict[str, str]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("transactional translation was not an object")
    return {str(key): value for key, value in parsed.items()}


def _validate(source: dict[str, str], translated: dict[str, str]) -> dict[str, str]:
    if set(translated) != set(source):
        raise ValueError("transactional translation keys changed")
    output: dict[str, str] = {}
    for key, source_value in source.items():
        value = translated.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"invalid transactional translation value: {key}")
        normalized = value.strip()
        if sorted(_PLACEHOLDER_RE.findall(normalized)) != sorted(_PLACEHOLDER_RE.findall(source_value)):
            raise ValueError(f"transactional translation placeholders changed: {key}")
        output[key] = normalized
    return output


async def _translate(locale: str, source: dict[str, str]) -> dict[str, str]:
    spec = locale_specs().get(locale.lower())
    language_code = spec.language_code if spec else locale.split("-", 1)[0].lower()
    language = family_name(language_code)
    messages = [
        {
            "role": "system",
            "content": (
                "You are AGRO-AI's deterministic transactional localization engine. "
                f"Translate every JSON string value naturally into {language} ({locale}). "
                "Return one JSON object only. Preserve every key exactly. Preserve placeholders "
                "in braces exactly. Preserve AGRO-AI, product names, URLs, units, numbers, and "
                "security meaning. Do not add explanations."
            ),
        },
        {"role": "user", "content": json.dumps(source, ensure_ascii=False, separators=(",", ":"))},
    ]
    result, _selection = await ModelRouter().run(
        task="ui_translation",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=1800,
        timeout_seconds=5,
        max_model_attempts=1,
    )
    if result.status != "ok" or not result.content.strip():
        raise RuntimeError(result.error or "transactional translation unavailable")
    return _validate(source, _decode_json_object(result.content))


def localize_transactional_strings(locale: str | None, source: dict[str, str]) -> dict[str, str]:
    """Translate fixed transactional copy with bounded latency and safe fallback.

    The caller is expected to provide any business-critical static locale catalog
    first (for example Brazilian onboarding Portuguese). This function supplies
    the scalable path for every other enabled AGRO-AI locale. Translation failure
    never blocks account creation or security email delivery.
    """

    try:
        canonical = canonical_ui_locale(locale or "en")
    except ValueError:
        canonical = "en"
    if canonical in {"auto", "en"}:
        return dict(source)

    static_copy = localize_static_transactional_strings(canonical, source)
    if static_copy is not None:
        return _validate(source, static_copy)

    logger.error("transactional_static_catalog_missing locale=%s", canonical)
    key = _cache_key(canonical, source)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached:
        return dict(cached)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running_loop = False
    else:
        running_loop = True
    if running_loop:
        logger.warning("transactional_i18n_async_context_fallback locale=%s", canonical)
        return dict(source)

    try:
        translated = asyncio.run(asyncio.wait_for(_translate(canonical, source), timeout=6.0))
    except Exception as exc:
        logger.warning("transactional_i18n_fallback locale=%s error=%s", canonical, exc)
        return dict(source)

    with _CACHE_LOCK:
        _CACHE[key] = dict(translated)
    return translated

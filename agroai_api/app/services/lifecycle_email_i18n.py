"""Localized copy for lifecycle onboarding email.

Policy (product requirement): a customer whose preferred language is one of
AGRO-AI's supported locales receives lifecycle email in that language. English
is used only for an unknown, unsupported or invalid locale. When localized
copy cannot be produced (no deterministic catalog and the platform translator
is unavailable) this module raises instead of returning English, so the send
is deferred and retried rather than silently delivered in the wrong language.

Resolution order for a supported non-English locale:
1. the deterministic catalog shared/localization/lifecycle-email-catalogs/<locale>.json
   (authored by the global i18n authoring workflow, fingerprint-locked to the
   English source exactly like the transactional catalogs);
2. the platform's existing translation infrastructure (ModelRouter
   "ui_translation", the engine behind transactional runtime localization),
   validated key-by-key with placeholders preserved, cached per process.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from functools import lru_cache
from pathlib import Path

from app.services.language_registry import canonical_ui_locale, family_name, locale_specs, target_ui_locales
from app.services.transactional_i18n import _decode_json_object, _validate

logger = logging.getLogger("agroai.lifecycle_email")

_REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATH = _REPO_ROOT / "shared" / "localization" / "lifecycle-email-source.json"
CATALOG_DIR = _REPO_ROOT / "shared" / "localization" / "lifecycle-email-catalogs"
_RUNTIME_CHUNK = 14
_RUNTIME_CACHE: dict[str, dict[str, str]] = {}
_RUNTIME_LOCK = threading.Lock()


class LifecycleLocalizationUnavailable(RuntimeError):
    """Localized copy for a supported locale could not be produced right now."""


def fingerprint(catalog: dict[str, str]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1)
def source_envelope() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def source_catalog() -> dict[str, str]:
    return dict(source_envelope()["catalog"])


def resolve_locale(*preferences: str | None) -> str:
    """The first explicit, supported preference wins; unknown or invalid values fall back to English."""
    supported = set(target_ui_locales()) - {"auto"}
    for value in preferences:
        raw = str(value or "").strip()
        if not raw or raw.lower() == "auto":
            continue
        if raw.lower() in {"pt", "pt-pt"}:
            raw = "pt-BR" if raw.lower() == "pt" else raw
        try:
            canonical = canonical_ui_locale(raw)
        except ValueError:
            continue
        if canonical in supported:
            return canonical
    return "en"


@lru_cache(maxsize=128)
def _static_catalog(locale: str) -> dict[str, str] | None:
    path = CATALOG_DIR / f"{locale}.json"
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    source = source_envelope()
    english = source["catalog"]
    if (
        envelope.get("schemaVersion") != 1
        or envelope.get("locale") != locale
        or envelope.get("status") != "complete-generated"
        or envelope.get("sourceVersion") != source.get("version")
        or envelope.get("sourceFingerprint") != fingerprint(english)
    ):
        return None
    catalog = envelope.get("catalog")
    if not isinstance(catalog, dict):
        return None
    try:
        return _validate(english, {str(k): v for k, v in catalog.items()})
    except ValueError:
        return None


async def _translate_chunk(locale: str, chunk: dict[str, str]) -> dict[str, str]:
    from app.services.model_router import ModelRouter

    spec = locale_specs().get(locale.lower())
    language = family_name(spec.language_code if spec else locale.split("-", 1)[0].lower())
    messages = [
        {
            "role": "system",
            "content": (
                "You are AGRO-AI's localization engine for customer onboarding email to agricultural "
                f"professionals. Translate every JSON string value naturally and professionally into {language} ({locale}). "
                "Return one JSON object only. Preserve every key exactly. Preserve placeholders in braces exactly. "
                "Keep AGRO-AI, product names (Ask AGRO-AI, Field Intelligence, Market Intelligence), plan names, "
                "URLs, units and numbers unchanged. Do not add explanations."
            ),
        },
        {"role": "user", "content": json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))},
    ]
    result, _selection = await ModelRouter().run(
        task="ui_translation",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=2400,
        timeout_seconds=25,
        max_model_attempts=2,
    )
    if result.status != "ok" or not result.content.strip():
        raise RuntimeError(result.error or "translation unavailable")
    return _validate(chunk, _decode_json_object(result.content))


def _runtime_catalog(locale: str) -> dict[str, str]:
    english = source_catalog()
    key = f"{locale}:{fingerprint(english)}"
    with _RUNTIME_LOCK:
        cached = _RUNTIME_CACHE.get(key)
    if cached:
        return dict(cached)
    items = sorted(english.items())
    translated: dict[str, str] = {}

    async def run() -> None:
        for start in range(0, len(items), _RUNTIME_CHUNK):
            translated.update(await _translate_chunk(locale, dict(items[start:start + _RUNTIME_CHUNK])))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:  # pragma: no cover - lifecycle sends run in worker threads, never on the event loop
        raise LifecycleLocalizationUnavailable(f"runtime translation unavailable in async context ({locale})")
    try:
        asyncio.run(asyncio.wait_for(run(), timeout=180))
        catalog = _validate(english, translated)
    except Exception as exc:
        raise LifecycleLocalizationUnavailable(f"{locale}: {exc.__class__.__name__}") from exc
    with _RUNTIME_LOCK:
        _RUNTIME_CACHE[key] = dict(catalog)
    logger.warning("lifecycle_email_runtime_localization locale=%s keys=%s", locale, len(catalog))
    return catalog


def localized_copy(locale: str) -> tuple[dict[str, str], str]:
    """Complete localized copy for ``locale`` and how it was obtained ("source", "catalog", "runtime")."""
    if locale == "en":
        return source_catalog(), "source"
    static = _static_catalog(locale)
    if static is not None:
        return static, "catalog"
    logger.error("lifecycle_email_catalog_missing locale=%s", locale)
    return _runtime_catalog(locale), "runtime"


_UI_CATALOG_DIR = _REPO_ROOT / "shared" / "localization" / "catalogs"
# Product surfaces, named exactly as the portal navigation names them.
PRODUCT_LABELS = {
    "ask_name": "Ask AGRO-AI",
    "field_name": "Field Intelligence",
    "market_name": "Market Intelligence",
    "plan_free": "Free",
    "plan_professional": "Professional",
    "plan_team": "Team",
    "plan_network": "Network",
}
_UI_KEYS = {
    "Ask AGRO-AI": "askAgroAi",
    "Field Intelligence": "fieldIntelligence",
    "Free": "dynamic.shared.free",
    "Professional": "dynamic.shared.professional",
    "Team": "dynamic.shared.team",
    "Network": "dynamic.shared.network",
}


@lru_cache(maxsize=128)
def _ui_catalog(locale: str) -> dict:
    try:
        envelope = json.loads((_UI_CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    catalog = envelope.get("catalog", envelope)
    return catalog if isinstance(catalog, dict) else {}


def product_labels(locale: str) -> dict[str, str]:
    """Localized product and plan names from the deployed portal UI catalog for ``locale``.

    Emails then use exactly the labels the customer sees in the portal. The UI
    inventory keys literal strings by sha256 of their English text.
    """
    if locale == "en":
        return dict(PRODUCT_LABELS)
    catalog = _ui_catalog(locale)
    labels = {}
    for placeholder, english in PRODUCT_LABELS.items():
        candidates = [_UI_KEYS.get(english), "literal." + hashlib.sha256(english.encode("utf-8")).hexdigest()[:16]]
        value = next((catalog.get(key) for key in candidates if key and isinstance(catalog.get(key), str) and catalog.get(key).strip()), None)
        labels[placeholder] = value or english
    return labels


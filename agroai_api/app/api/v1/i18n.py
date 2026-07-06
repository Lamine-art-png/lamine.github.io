from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import AuthContext, get_auth_context
from app.services.language_registry import enabled_ui_locales, family_direction, family_name, locale_specs
from app.services.model_router import ModelRouter

router = APIRouter(tags=["i18n"])

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CANONICAL_CATALOG_PATH = _REPO_ROOT / "shared" / "ui-catalog.en.json"
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_MAX_KEYS = 250
_MAX_VALUE_CHARS = 2_000
_MAX_SOURCE_CHARS = 60_000
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


class CatalogRequest(BaseModel):
    locale: str = Field(min_length=2, max_length=40)
    source: dict[str, str]

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or len(value) > _MAX_KEYS:
            raise ValueError(f"source must contain 1..{_MAX_KEYS} entries")
        total = 0
        for key, text in value.items():
            if not key or len(key) > 160:
                raise ValueError("invalid translation key")
            if not isinstance(text, str) or len(text) > _MAX_VALUE_CHARS:
                raise ValueError("invalid translation value")
            total += len(key) + len(text)
        if total > _MAX_SOURCE_CHARS:
            raise ValueError("translation source is too large")
        return value


@lru_cache(maxsize=1)
def canonical_source_catalog() -> dict[str, str]:
    raw = json.loads(_CANONICAL_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw or not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
        raise RuntimeError("canonical_ui_catalog_invalid")
    return raw


def _enabled_locale_payloads() -> list[dict[str, Any]]:
    specs = locale_specs()
    payloads: list[dict[str, Any]] = []
    for code in enabled_ui_locales():
        if code == "auto":
            payloads.append({"code": "auto", "language_code": "auto", "name": "Browser default", "direction": "ltr"})
            continue
        spec = specs.get(code.lower())
        language_code = spec.language_code if spec else code.split("-", 1)[0].lower()
        payloads.append({"code": code, "language_code": language_code, "name": family_name(language_code), "direction": spec.direction if spec else family_direction(language_code)})
    return payloads


def _cache_key(locale: str, source: dict[str, str]) -> str:
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{locale}:{digest}"


def _placeholders(value: str) -> Counter[str]:
    return Counter(_PLACEHOLDER_RE.findall(value))


def _validate_translated_catalog(source: dict[str, str], translated: Any) -> dict[str, str]:
    if not isinstance(translated, dict):
        raise ValueError("translated catalog is not an object")
    if set(translated) != set(source):
        raise ValueError("translated catalog keys do not match source keys")
    output: dict[str, str] = {}
    for key, source_value in source.items():
        value = translated.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"invalid translated value for {key}")
        normalized = value.strip()
        if _placeholders(normalized) != _placeholders(source_value):
            raise ValueError(f"translated placeholders do not match source for {key}")
        output[key] = normalized
    return output


@router.get("/i18n/languages")
def get_ui_languages() -> dict[str, Any]:
    languages = _enabled_locale_payloads()
    return {"status": "ok", "count": len(languages), "languages": languages}


@router.post("/i18n/catalog")
async def translate_ui_catalog(payload: CatalogRequest, _ctx: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    enabled = {code.lower(): code for code in enabled_ui_locales()}
    requested = payload.locale.strip().replace("_", "-")
    canonical = enabled.get(requested.lower())
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "unsupported_ui_locale", "locale": requested})
    if canonical == "auto":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "auto_locale_requires_browser_resolution"})

    source = canonical_source_catalog()
    if payload.source != source:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "ui_source_catalog_mismatch", "action": "refresh_portal_release"})
    if canonical == "en":
        return {"status": "ok", "locale": canonical, "catalog": source, "source": "identity"}

    key = _cache_key(canonical, source)
    cached = _CACHE.get(key)
    if cached and cached[0] > time.time():
        return {"status": "ok", "locale": canonical, "catalog": cached[1], "source": "memory_cache"}

    spec = locale_specs().get(canonical.lower())
    language_code = spec.language_code if spec else canonical.split("-", 1)[0].lower()
    language = family_name(language_code)
    source_json = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    messages = [
        {"role": "system", "content": "You are AGRO-AI's deterministic enterprise UI localization engine. " + f"Translate every JSON string value into {language} ({canonical}). " + "Return one JSON object only. Preserve every key exactly. Preserve placeholders such as {recipient}, {title}, and {level} exactly. Preserve AGRO-AI, product names, URLs, units, numbers, and Markdown syntax. Do not add explanations."},
        {"role": "user", "content": source_json},
    ]
    result, selection = await ModelRouter().run(task="ui_translation", messages=messages, temperature=0.0, response_format={"type": "json_object"}, max_tokens=8_000, timeout_seconds=45, max_model_attempts=3)
    if result.status != "ok" or not result.content.strip():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "ui_catalog_generation_unavailable", "locale": canonical, "provider": result.provider, "model": result.model})
    try:
        translated = _validate_translated_catalog(source, json.loads(result.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"code": "invalid_ui_catalog_generation", "locale": canonical, "reason": str(exc)}) from exc

    _CACHE[key] = (time.time() + _CACHE_TTL_SECONDS, translated)
    return {"status": "ok", "locale": canonical, "catalog": translated, "source": "generated", "provider": result.provider, "model": result.model or selection.model}

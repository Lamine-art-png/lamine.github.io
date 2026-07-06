from __future__ import annotations

import asyncio
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
_PLACEHOLDER_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_KEYS = 250
_MAX_VALUE_CHARS = 2_000
_MAX_SOURCE_CHARS = 60_000
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_TRANSLATION_CHUNK_SIZE = 18
_MAX_CHUNK_ATTEMPTS = 2
_MAX_PARALLEL_MODEL_CALLS = 3
_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_CACHE_LOCKS: dict[str, asyncio.Lock] = {}


class CatalogRequest(BaseModel):
    locale: str = Field(min_length=2, max_length=40)
    source: dict[str, str] | None = None

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if not value or len(value) > _MAX_KEYS:
            raise ValueError(f"source must contain 1..{_MAX_KEYS} entries")
        total = 0
        for key, text_value in value.items():
            if not key or len(key) > 160:
                raise ValueError("invalid translation key")
            if not isinstance(text_value, str) or len(text_value) > _MAX_VALUE_CHARS:
                raise ValueError("invalid translation value")
            total += len(key) + len(text_value)
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


def _placeholder_signature(value: str) -> Counter[str]:
    tokens: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "}":
            raise ValueError("malformed placeholder braces")
        if char != "{":
            index += 1
            continue
        end = value.find("}", index + 1)
        if end < 0:
            raise ValueError("malformed placeholder braces")
        name = value[index + 1 : end]
        if _PLACEHOLDER_NAME_RE.fullmatch(name) is None:
            raise ValueError("malformed placeholder braces")
        tokens.append("{" + name + "}")
        index = end + 1
    return Counter(tokens)


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
        try:
            source_signature = _placeholder_signature(source_value)
            translated_signature = _placeholder_signature(normalized)
        except ValueError as exc:
            raise ValueError(f"malformed placeholders for {key}") from exc
        if translated_signature != source_signature:
            raise ValueError(f"translated placeholders do not match source for {key}")
        output[key] = normalized
    return output


def _decode_json_object(content: str) -> dict[str, Any]:
    text_value = content.strip()
    if text_value.startswith("```"):
        text_value = re.sub(r"^```(?:json)?\s*", "", text_value, flags=re.IGNORECASE)
        text_value = re.sub(r"\s*```$", "", text_value)
    try:
        parsed = json.loads(text_value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text_value.find("{")
    end = text_value.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text_value[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("translation model did not return a JSON object")


def _chunks(source: dict[str, str], size: int = _TRANSLATION_CHUNK_SIZE) -> list[dict[str, str]]:
    items = list(source.items())
    return [dict(items[index : index + size]) for index in range(0, len(items), size)]


async def _translate_chunk_once(router: ModelRouter, semaphore: asyncio.Semaphore, *, canonical: str, language: str, chunk: dict[str, str]) -> tuple[dict[str, str], str, str | None]:
    source_json = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    messages = [
        {"role": "system", "content": "You are AGRO-AI's deterministic enterprise UI localization engine. " + f"Translate every JSON string value into {language} ({canonical}). " + "Return one JSON object only. Preserve every key exactly. Preserve every placeholder token exactly, including braces and multiplicity. Preserve AGRO-AI, product names, URLs, units, numbers, and Markdown syntax. Translate interface copy naturally and concisely. Do not add explanations."},
        {"role": "user", "content": source_json},
    ]
    async with semaphore:
        result, selection = await router.run(task="ui_translation", messages=messages, temperature=0.0, response_format={"type": "json_object"}, max_tokens=4_000, timeout_seconds=35, max_model_attempts=3)
    if result.status != "ok" or not result.content.strip():
        raise ValueError(f"translation model unavailable: {result.provider}/{result.model}")
    translated = _validate_translated_catalog(chunk, _decode_json_object(result.content))
    return translated, result.provider, result.model or selection.model


async def _translate_chunk_resilient(router: ModelRouter, semaphore: asyncio.Semaphore, *, canonical: str, language: str, chunk: dict[str, str]) -> tuple[dict[str, str], set[str], set[str]]:
    last_error: Exception | None = None
    for _attempt in range(_MAX_CHUNK_ATTEMPTS):
        try:
            translated, provider, model = await _translate_chunk_once(router, semaphore, canonical=canonical, language=language, chunk=chunk)
            return translated, {provider}, {model} if model else set()
        except Exception as exc:
            last_error = exc
    if len(chunk) == 1:
        raise ValueError(f"translation key failed after retries: {next(iter(chunk))}: {last_error}") from last_error
    items = list(chunk.items())
    midpoint = len(items) // 2
    left = dict(items[:midpoint])
    right = dict(items[midpoint:])
    left_result, right_result = await asyncio.gather(
        _translate_chunk_resilient(router, semaphore, canonical=canonical, language=language, chunk=left),
        _translate_chunk_resilient(router, semaphore, canonical=canonical, language=language, chunk=right),
    )
    left_catalog, left_providers, left_models = left_result
    right_catalog, right_providers, right_models = right_result
    return {**left_catalog, **right_catalog}, left_providers | right_providers, left_models | right_models


async def _translate_catalog(canonical: str, language: str, source: dict[str, str]) -> tuple[dict[str, str], set[str], set[str], int]:
    model_router = ModelRouter()
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_MODEL_CALLS)
    chunks = _chunks(source)
    results = await asyncio.gather(*[_translate_chunk_resilient(model_router, semaphore, canonical=canonical, language=language, chunk=chunk) for chunk in chunks])
    catalog: dict[str, str] = {}
    providers: set[str] = set()
    models: set[str] = set()
    for translated, chunk_providers, chunk_models in results:
        catalog.update(translated)
        providers.update(chunk_providers)
        models.update(chunk_models)
    return _validate_translated_catalog(source, catalog), providers, models, len(chunks)


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
    if payload.source is not None and payload.source != source:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "ui_source_catalog_mismatch", "action": "refresh_portal_release"})
    if canonical == "en":
        return {"status": "ok", "locale": canonical, "catalog": source, "source": "identity"}
    key = _cache_key(canonical, source)
    cached = _CACHE.get(key)
    if cached and cached[0] > time.time():
        return {"status": "ok", "locale": canonical, "catalog": cached[1], "source": "memory_cache"}
    lock = _CACHE_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.time():
            return {"status": "ok", "locale": canonical, "catalog": cached[1], "source": "memory_cache"}
        spec = locale_specs().get(canonical.lower())
        language_code = spec.language_code if spec else canonical.split("-", 1)[0].lower()
        language = family_name(language_code)
        try:
            translated, providers, models, chunk_count = await _translate_catalog(canonical, language, source)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "ui_catalog_generation_unavailable", "locale": canonical, "reason": str(exc)}) from exc
        _CACHE[key] = (time.time() + _CACHE_TTL_SECONDS, translated)
        return {"status": "ok", "locale": canonical, "catalog": translated, "source": "generated_chunked", "chunks": chunk_count, "providers": sorted(providers), "models": sorted(models)}

"""Resilient translation-only fallback for UI catalogs.

This service is deliberately separate from the general AGRO-AI chat model path.
If the configured model provider is unavailable, UI localization can still use a
translation-specific network endpoint, with exact key and placeholder integrity
validated by the caller.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

_GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_TARGET_OVERRIDES = {
    "fr-FR": "fr",
    "zh": "zh-CN",
}
_MAX_BATCH_CHARS = 1400
_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class TranslationFallbackResult:
    catalog: dict[str, str]
    provider: str
    model: str


class TranslationFallbackError(RuntimeError):
    pass


def _target_code(locale: str) -> str:
    canonical = locale.strip().replace("_", "-")
    return _TARGET_OVERRIDES.get(canonical, canonical.split("-", 1)[0])


def _protect_placeholders(value: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}
    parts: list[str] = []
    cursor = 0
    for index, match in enumerate(_PLACEHOLDER_RE.finditer(value)):
        marker = f"\ue210{index:04d}\ue211"
        parts.append(value[cursor : match.start()])
        parts.append(marker)
        replacements[marker] = match.group(0)
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts), replacements


def _restore_placeholders(value: str, replacements: dict[str, str]) -> str:
    restored = value
    for marker, original in replacements.items():
        if marker not in restored:
            raise TranslationFallbackError(f"placeholder marker lost during translation: {original}")
        restored = restored.replace(marker, original)
    return restored


def _decode_google_payload(payload: Any) -> str:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise TranslationFallbackError("translation endpoint returned an unexpected payload")
    segments: list[str] = []
    for item in payload[0]:
        if isinstance(item, list) and item and isinstance(item[0], str):
            segments.append(item[0])
    translated = "".join(segments).strip()
    if not translated:
        raise TranslationFallbackError("translation endpoint returned empty content")
    return translated


async def _translate_text(client: httpx.AsyncClient, text: str, target: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.get(
                _GOOGLE_TRANSLATE_URL,
                params={"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": text},
                headers={"Accept": "application/json", "User-Agent": "AGRO-AI-UI-Translation/1.0"},
            )
            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                raise httpx.HTTPStatusError(
                    f"transient translation status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return _decode_google_payload(response.json())
        except (httpx.HTTPError, json.JSONDecodeError, TranslationFallbackError) as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(attempt * 0.75)
    raise TranslationFallbackError(f"network translation failed: {last_error}") from last_error


def _batch_marker(seed: str, index: int) -> str:
    return f"\ue000{seed}{index:04d}\ue001"


async def _translate_items(
    client: httpx.AsyncClient,
    items: list[tuple[str, str]],
    target: str,
    *,
    depth: int = 0,
) -> dict[str, str]:
    if not items:
        return {}
    if len(items) == 1:
        key, source_value = items[0]
        protected, placeholders = _protect_placeholders(source_value)
        translated = await _translate_text(client, protected, target)
        return {key: _restore_placeholders(translated, placeholders).strip()}

    seed_material = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    seed = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:12]
    protected_values: list[tuple[str, str, dict[str, str], str]] = []
    combined_parts: list[str] = []
    for index, (key, source_value) in enumerate(items):
        protected, placeholders = _protect_placeholders(source_value)
        marker = _batch_marker(seed, index)
        protected_values.append((key, protected, placeholders, marker))
        combined_parts.append(marker)
        combined_parts.append(protected)
    combined = "\n".join(combined_parts)

    if len(combined) > _MAX_BATCH_CHARS:
        midpoint = len(items) // 2
        left = await _translate_items(client, items[:midpoint], target, depth=depth + 1)
        right = await _translate_items(client, items[midpoint:], target, depth=depth + 1)
        return {**left, **right}

    try:
        translated = await _translate_text(client, combined, target)
        positions: list[tuple[int, str, dict[str, str], str]] = []
        for key, _protected, placeholders, marker in protected_values:
            position = translated.find(marker)
            if position < 0:
                raise TranslationFallbackError(f"batch marker lost for key {key}")
            positions.append((position, key, placeholders, marker))
        positions.sort(key=lambda item: item[0])

        output: dict[str, str] = {}
        for index, (position, key, placeholders, marker) in enumerate(positions):
            start = position + len(marker)
            end = positions[index + 1][0] if index + 1 < len(positions) else len(translated)
            value = translated[start:end].strip()
            if not value:
                raise TranslationFallbackError(f"empty batch translation for key {key}")
            output[key] = _restore_placeholders(value, placeholders).strip()
        if set(output) != {key for key, _ in items}:
            raise TranslationFallbackError("batch translation key reconciliation failed")
        return output
    except TranslationFallbackError:
        if depth >= 8:
            raise
        midpoint = len(items) // 2
        left = await _translate_items(client, items[:midpoint], target, depth=depth + 1)
        right = await _translate_items(client, items[midpoint:], target, depth=depth + 1)
        return {**left, **right}


async def translate_ui_mapping(locale: str, source: dict[str, str]) -> TranslationFallbackResult:
    if not source:
        raise TranslationFallbackError("translation source is empty")
    target = _target_code(locale)
    timeout = httpx.Timeout(25.0, connect=10.0)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
        catalog = await _translate_items(client, list(source.items()), target)
    return TranslationFallbackResult(
        catalog=catalog,
        provider="google_translate_fallback",
        model="translate_a/single",
    )

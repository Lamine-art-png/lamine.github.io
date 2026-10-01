#!/usr/bin/env python3
"""Deterministic build-time translation helper using AGRO-AI's public provider path.

This is authoring-only. Catalogs are validated and committed before they can be
advertised to customers; no production language switch depends on this service.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
MAX_BATCH_CHARS = 1650
ITEM_RE = re.compile(r"<<<\s*AGROAI_ITEM_(\d{4})\s*>>>", re.I)
PROTECTED_RE = re.compile(
    r"(\{[A-Za-z_][A-Za-z0-9_]*\}|https?://[^\s]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\b(?:AGRO-AI|API|OAuth|CSV|PDF|JSON|OpenET|WiseConn|Talgil|Stripe|TEST|LIVE|GPT)\b)"
)


def _item_marker(index: int) -> str:
    return f"<<<AGROAI_ITEM_{index:04d}>>>"


def _keep_marker(index: int) -> str:
    return f"<<<AGROAI_KEEP_{index:04d}>>>"


def _normalize_markers(value: str) -> str:
    # Providers occasionally drop or widen bracket runs or use full-width
    # brackets around protection markers; accept any 1-3 bracket variant.
    return re.sub(
        r"[<＜《〈]{1,3}\s*AGROAI[_ ]?(ITEM|KEEP)[_ ]?(\d{4})\s*[>＞》〉]{1,3}",
        r"<<<AGROAI_\1_\2>>>",
        value,
        flags=re.I,
    )


def _pack(entries: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    packs: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    chars = 0
    for entry in entries:
        cost = len(entry[1]) + 48
        if current and chars + cost > MAX_BATCH_CHARS:
            packs.append(current)
            current = []
            chars = 0
        current.append(entry)
        chars += cost
    if current:
        packs.append(current)
    return packs


def _google_locale(locale: str) -> str:
    root = locale.split("-", 1)[0].lower()
    return "zh-CN" if root == "zh" else root


def _translate_pack(locale: str, entries: list[tuple[str, str]]) -> dict[str, str]:
    protected: list[str] = []
    encoded_lines: list[str] = []
    keys: list[str] = []

    for index, (key, source) in enumerate(entries):
        def repl(match: re.Match[str]) -> str:
            marker = _keep_marker(len(protected))
            protected.append(match.group(0))
            return marker
        safe = PROTECTED_RE.sub(repl, source)
        encoded_lines.append(f"{_item_marker(index)}\n{safe}")
        keys.append(key)

    query = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "en",
        "tl": _google_locale(locale),
        "dt": "t",
        "q": "\n".join(encoded_lines),
    })
    request = urllib.request.Request(
        f"{GOOGLE_ENDPOINT}?{query}",
        headers={"accept": "application/json", "user-agent": "AGRO-AI-Localization-Authoring/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)

    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise RuntimeError("public_translation_invalid_payload")
    translated = "".join(
        str(segment[0]) if isinstance(segment, list) and segment and isinstance(segment[0], str) else ""
        for segment in payload[0]
    ).strip()
    translated = _normalize_markers(html.unescape(translated))
    if not translated:
        raise RuntimeError("public_translation_empty")

    output: dict[str, str] = {}
    for index, key in enumerate(keys):
        start_marker = _item_marker(index)
        start = translated.find(start_marker)
        if start < 0:
            raise RuntimeError(f"public_translation_missing_item_marker:{index}")
        content_start = start + len(start_marker)
        next_marker = _item_marker(index + 1) if index + 1 < len(keys) else ""
        end = translated.find(next_marker, content_start) if next_marker else len(translated)
        if end < content_start:
            raise RuntimeError(f"public_translation_missing_boundary:{index}")
        value = translated[content_start:end].strip()
        for keep_index, original in enumerate(protected):
            value = value.replace(_keep_marker(keep_index), original)
        if re.search(r"AGROAI[_ ]?(?:KEEP|ITEM)", value, flags=re.I):
            raise RuntimeError(f"public_translation_unrestored_marker:{index}")
        if not value:
            raise RuntimeError(f"public_translation_empty_item:{index}")
        output[key] = value
    return output


def _suspicious(pack_source: dict[str, str], pack_output: dict[str, str]) -> list[str]:
    """Items a packed request likely hallucinated: loops, or one output reused for different inputs."""
    from i18n_quality import degenerate

    inputs_by_output: dict[str, set[str]] = {}
    for key, value in pack_output.items():
        inputs_by_output.setdefault(value.strip(), set()).add(pack_source[key].strip().lower())
    return [
        key for key, value in pack_output.items()
        if degenerate(value, pack_source[key]) or len(inputs_by_output[value.strip()]) > 1
    ]


def translate_catalog(locale: str, source: dict[str, str]) -> dict[str, str]:
    from i18n_quality import degenerate

    if locale == "en":
        return dict(source)
    output: dict[str, str] = {}
    for pack in _pack(list(source.items())):
        translated = _translate_pack(locale, pack)
        # Low-resource models hallucinate on long packed inputs; re-ask those
        # items one at a time and refuse anything that is still degenerate.
        for key in _suspicious(dict(pack), translated):
            single = _translate_pack(locale, [(key, source[key])])[key]
            if degenerate(single, source[key]):
                raise RuntimeError(f"public_translation_degenerate:{key}")
            translated[key] = single
        output.update(translated)
    if set(output) != set(source):
        raise RuntimeError("public_translation_key_mismatch")
    return output

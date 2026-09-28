#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "shared" / "supported-locales.json"
UI_SOURCE_PATH = ROOT / "shared" / "localization" / "source.json"
UI_DIR = ROOT / "shared" / "localization" / "catalogs"
TX_SOURCE_PATH = ROOT / "shared" / "localization" / "transactional-source.json"
TX_DIR = ROOT / "shared" / "localization" / "transactional-catalogs"
LEGAL_DIR = ROOT / "platform-api" / "legal" / "localized"


def stable_fingerprint(catalog: dict[str, str]) -> str:
    raw = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def json_file(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def ui_ready(locale: str, source: dict) -> bool:
    if locale == "en":
        return True
    envelope = json_file(UI_DIR / f"{locale}.json")
    if not envelope:
        return False
    catalog = envelope.get("catalog")
    return bool(
        envelope.get("schemaVersion") == 2
        and envelope.get("locale") == locale
        and envelope.get("status") == "complete-generated"
        and envelope.get("sourceFingerprint") == source.get("sourceFingerprint")
        and isinstance(catalog, dict)
        and set(catalog) == set(source.get("catalog") or {})
    )


def transactional_ready(locale: str, source: dict) -> bool:
    if locale == "en":
        return True
    envelope = json_file(TX_DIR / f"{locale}.json")
    if not envelope:
        return False
    catalog = envelope.get("catalog")
    expected = stable_fingerprint(source.get("catalog") or {})
    return bool(
        envelope.get("schemaVersion") == 1
        and envelope.get("locale") == locale
        and envelope.get("status") == "complete-generated"
        and envelope.get("sourceVersion") == source.get("version")
        and envelope.get("sourceFingerprint") == expected
        and isinstance(catalog, dict)
        and set(catalog) == set(source.get("catalog") or {})
    )


def legal_ready(locale: str) -> bool:
    if locale == "en":
        return True
    base = LEGAL_DIR / locale
    for slug in ("terms-of-service", "privacy-policy"):
        html = base / f"{slug}.html"
        meta = json_file(base / f"{slug}.meta.json")
        if not html.exists() or html.stat().st_size < 1000 or not meta:
            return False
        if meta.get("schemaVersion") != 1 or meta.get("locale") != locale or meta.get("status") != "complete-generated":
            return False
        if not isinstance(meta.get("sourceSha256"), str) or len(meta["sourceSha256"]) != 64:
            return False
        if int(meta.get("translatedTextNodes") or 0) < 10:
            return False
    return True


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ui_source = json.loads(UI_SOURCE_PATH.read_text(encoding="utf-8"))
    tx_source = json.loads(TX_SOURCE_PATH.read_text(encoding="utf-8"))
    target = list(manifest.get("targetUiLocales") or manifest.get("enabledUiLocales") or ["auto", "en"])
    if "auto" not in target:
        target.insert(0, "auto")
    if "en" not in target:
        target.insert(1 if target and target[0] == "auto" else 0, "en")

    ready = []
    matrix = {}
    for locale in target:
        if locale == "auto":
            continue
        status = {
            "ui": ui_ready(locale, ui_source),
            "transactional": transactional_ready(locale, tx_source),
            "legal": legal_ready(locale),
        }
        status["ready"] = all(status.values())
        matrix[locale] = status
        if status["ready"]:
            ready.append(locale)

    if "en" not in ready:
        raise SystemExit("English baseline unexpectedly unavailable")

    manifest["enabledUiLocales"] = ["auto", *ready]
    manifest["catalogCompleteLocales"] = ready
    manifest["dynamicCatalogLocales"] = []
    manifest["uiTranslationPolicy"] = "versioned-static-complete-catalogs"
    qa = manifest.setdefault("qa", {})
    qa["staticCompleteLocales"] = ready
    qa["linguisticCompleteLocales"] = ready
    qa["browserCompleteLocales"] = ready
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    missing = [locale for locale, state in matrix.items() if not state["ready"]]
    print(json.dumps({
        "status": "ok",
        "target": len([x for x in target if x != "auto"]),
        "advertised": len(ready),
        "ready": ready,
        "missing": missing,
        "matrix": matrix,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

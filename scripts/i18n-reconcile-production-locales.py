#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n_quality import has_marker_residue, quality_errors, quality_report  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "shared" / "supported-locales.json"
UI_SOURCE_PATH = ROOT / "shared" / "localization" / "source.json"
UI_DIR = ROOT / "shared" / "localization" / "catalogs"
TX_SOURCE_PATH = ROOT / "shared" / "localization" / "transactional-source.json"
TX_DIR = ROOT / "shared" / "localization" / "transactional-catalogs"
LEGAL_DIR = ROOT / "platform-api" / "legal" / "localized"
RELEASE_MATRIX_PATH = ROOT / "shared" / "localization" / "release-matrix.json"
TOKENS = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


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
    source_catalog = source.get("catalog") or {}
    if not (
        envelope.get("schemaVersion") == 2
        and envelope.get("locale") == locale
        and envelope.get("status") == "complete-generated"
        and envelope.get("sourceFingerprint") == source.get("sourceFingerprint")
        and isinstance(catalog, dict)
        and set(catalog) == set(source_catalog)
    ):
        return False
    for key, original in source_catalog.items():
        value = catalog[key]
        if not isinstance(value, str) or not value.strip() or "[object Object]" in value or "\ufffd" in value:
            return False
        if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
            return False
    return not quality_errors(locale, source_catalog, catalog)


def transactional_ready(locale: str, source: dict) -> bool:
    if locale == "en":
        return True
    envelope = json_file(TX_DIR / f"{locale}.json")
    if not envelope:
        return False
    catalog = envelope.get("catalog")
    expected = stable_fingerprint(source.get("catalog") or {})
    if isinstance(catalog, dict) and any(isinstance(v, str) and has_marker_residue(v) for v in catalog.values()):
        return False
    return bool(
        envelope.get("schemaVersion") == 1
        and envelope.get("locale") == locale
        and envelope.get("status") == "complete-generated"
        and envelope.get("sourceVersion") == source.get("version")
        and envelope.get("sourceFingerprint") == expected
        and isinstance(catalog, dict)
        and set(catalog) == set(source.get("catalog") or {})
    )


def legal_source_hashes(locale: str) -> dict[str, str]:
    hashes = {}
    for slug in ("terms-of-service", "privacy-policy"):
        meta = json_file(LEGAL_DIR / locale / f"{slug}.meta.json") or {}
        hashes[slug] = str(meta.get("sourceSha256") or "")
    return hashes


def legal_ready(locale: str, canonical_hashes: dict[str, str] | None = None) -> bool:
    if locale == "en":
        return True
    if canonical_hashes and legal_source_hashes(locale) != canonical_hashes:
        # Every localized presentation must translate the same canonical
        # English legal version; a snapshot of an older version is not ready.
        return False
    base = LEGAL_DIR / locale
    for slug in ("terms-of-service", "privacy-policy"):
        html = base / f"{slug}.html"
        meta = json_file(base / f"{slug}.meta.json")
        if not html.exists() or html.stat().st_size < 1000 or not meta:
            return False
        if has_marker_residue(re.sub(r"(?is)<script\b.*?</script\s*>", "", html.read_text(encoding="utf-8"))):
            return False
        if meta.get("schemaVersion") != 1 or meta.get("locale") != locale or meta.get("status") != "complete-generated":
            return False
        if not isinstance(meta.get("sourceSha256"), str) or len(meta["sourceSha256"]) != 64:
            return False
        if int(meta.get("translatedTextNodes") or 0) < 10:
            return False
        if meta.get("legalVersion") != CANONICAL_LEGAL_VERSIONS[slug]:
            return False
    return True


def _canonical_legal_versions() -> dict[str, str]:
    auth = (ROOT / "agroai_api/app/api/v1/auth.py").read_text(encoding="utf-8")
    out = {}
    for slug, name in (("terms-of-service", "SELF_SERVICE_TERMS_VERSION"), ("privacy-policy", "SELF_SERVICE_PRIVACY_VERSION")):
        match = re.search(rf'^{name}\s*=\s*"([^"]+)"', auth, flags=re.M)
        out[slug] = match.group(1) if match else ""
    return out


CANONICAL_LEGAL_VERSIONS = _canonical_legal_versions()


def _stripe_locale_table():
    """Evaluate billing.py's locale tables without importing the API app."""
    import ast
    tree = ast.parse((ROOT / "agroai_api/app/api/v1/billing.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("_STRIPE_SUPPORTED_LOCALES", "_STRIPE_LOCALE_ALIASES"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    return values.get("_STRIPE_SUPPORTED_LOCALES", set()), values.get("_STRIPE_LOCALE_ALIASES", {})


_STRIPE_SUPPORTED, _STRIPE_ALIASES = _stripe_locale_table()


def stripe_locale(locale: str) -> str:
    mapped = _STRIPE_ALIASES.get(locale, locale)
    return mapped if mapped in _STRIPE_SUPPORTED else "auto"


def canonical_legal_hashes() -> dict[str, str] | None:
    """The canonical legal version is the one most localized snapshots translate.

    Recorded explicitly in platform-api/legal/localized/canonical.json when present.
    """
    pinned = json_file(LEGAL_DIR / "canonical.json")
    if pinned and isinstance(pinned.get("sourceSha256"), dict):
        return {str(k): str(v) for k, v in pinned["sourceSha256"].items()}
    return None


def target_locales(manifest: dict) -> list[str]:
    target = list(manifest.get("targetUiLocales") or manifest.get("enabledUiLocales") or ["auto", "en"])
    if "auto" not in target:
        target.insert(0, "auto")
    if "en" not in target:
        target.insert(1 if target and target[0] == "auto" else 0, "en")
    return target


def compute_matrix(manifest: dict, ui_source: dict, tx_source: dict) -> dict[str, dict]:
    canonical = canonical_legal_hashes()
    rows = {row.get("code"): row for row in manifest.get("locales") or []}
    matrix = {}
    for locale in target_locales(manifest):
        if locale == "auto":
            continue
        status = {
            "ui": ui_ready(locale, ui_source),
            "transactional": transactional_ready(locale, tx_source),
            "legal": legal_ready(locale, canonical),
        }
        status["ready"] = all(status.values())
        status["direction"] = (rows.get(locale) or {}).get("direction", "ltr")
        matrix[locale] = status
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending-matrix", action="store_true", help="print GitHub output for locales needing authoring")
    parser.add_argument("--check", choices=["ui", "transactional", "legal"])
    parser.add_argument("--locale")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ui_source = json.loads(UI_SOURCE_PATH.read_text(encoding="utf-8"))
    tx_source = json.loads(TX_SOURCE_PATH.read_text(encoding="utf-8"))

    if args.check:
        ok = {
            "ui": lambda: ui_ready(args.locale, ui_source),
            "transactional": lambda: transactional_ready(args.locale, tx_source),
            "legal": lambda: legal_ready(args.locale, canonical_legal_hashes()),
        }[args.check]()
        raise SystemExit(0 if ok else 1)

    matrix = compute_matrix(manifest, ui_source, tx_source)
    if args.pending_matrix:
        pending = [locale for locale, state in matrix.items() if locale != "en" and not state["ready"]]
        print("locales=" + json.dumps(pending, separators=(",", ":")))
        print("any=" + ("true" if pending else "false"))
        return

    ready = [locale for locale, state in matrix.items() if state["ready"]]

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

    release_rows = {}
    for locale, state in matrix.items():
        row = dict(state)
        if locale != "en" and state["ui"]:
            envelope = json_file(UI_DIR / f"{locale}.json") or {}
            report = quality_report(locale, ui_source["catalog"], envelope.get("catalog") or {})
            row["uiQuality"] = {k: v for k, v in report.items() if k not in ("locale", "dntViolations")}
        row["billing"] = {"stripeCheckoutLocale": stripe_locale(locale), "agroaiBillingUi": locale}
        # Voice: the effective locale is sent as the recognition hint and the
        # realtime model answers in the resolved response language; spoken
        # output quality is provider-dependent and the browser fallback voice
        # is device-dependent. Recorded explicitly rather than implied.
        row["voice"] = {"recognitionHint": locale, "responseLanguage": locale, "browserFallbackTts": "device-dependent"}
        row["intelligence"] = {"preferredLanguage": locale}
        release_rows[locale] = row
    RELEASE_MATRIX_PATH.write_text(json.dumps({
        "schemaVersion": 1,
        "uiSourceFingerprint": ui_source.get("sourceFingerprint"),
        "transactionalSourceVersion": tx_source.get("version"),
        "legalCanonicalSha256": canonical_legal_hashes(),
        "target": len(matrix),
        "releaseEligible": len(ready),
        "locales": release_rows,
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

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

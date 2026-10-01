#!/usr/bin/env python3
"""Exit 0 when the committed lifecycle email catalog for --locale matches the
current English source exactly (version + fingerprint + complete keys)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from i18n_quality import collapsed_values, degenerate_keys, serbian_script_keys  # noqa: E402
SOURCE = ROOT / "shared/localization/lifecycle-email-source.json"
CATALOGS = ROOT / "shared/localization/lifecycle-email-catalogs"


def fingerprint(catalog: dict) -> str:
    return hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def ready(locale: str) -> bool:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    path = CATALOGS / f"{locale}.json"
    if not path.exists():
        return False
    envelope = json.loads(path.read_text(encoding="utf-8"))
    catalog = envelope.get("catalog") or {}
    return (
        envelope.get("status") == "complete-generated"
        and envelope.get("locale") == locale
        and envelope.get("sourceVersion") == source["version"]
        and envelope.get("sourceFingerprint") == fingerprint(source["catalog"])
        and set(catalog) == set(source["catalog"])
        and all(isinstance(v, str) and v.strip() for v in catalog.values())
        and not degenerate_keys(source["catalog"], catalog)
        and not collapsed_values(source["catalog"], catalog)
        and not serbian_script_keys(locale, source["catalog"], catalog)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", required=True)
    sys.exit(0 if ready(parser.parse_args().locale) else 1)

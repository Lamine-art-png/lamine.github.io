#!/usr/bin/env python3
"""Content identity for release UI catalogs.

`sourceFingerprint` identifies the English source a catalog translates; it does
not change when only translated values change. `catalogSha256` identifies the
exact release artifact (locale + source fingerprint + every translated value),
is stamped into the catalog envelope (so it ships inside the deployed chunk),
and is what production verification compares.

  python3 scripts/i18n_catalog_identity.py --stamp   # (re)stamp all catalogs
  python3 scripts/i18n_catalog_identity.py --check   # fail on any stale stamp
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "shared" / "localization" / "catalogs"


def catalog_sha256(envelope: dict) -> str:
    identity = {
        "locale": envelope.get("locale"),
        "sourceFingerprint": envelope.get("sourceFingerprint"),
        "catalog": envelope.get("catalog") or {},
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stamped(envelope: dict) -> dict:
    """Return the envelope with catalogSha256 placed before the catalog body."""
    digest = catalog_sha256(envelope)
    out: dict = {}
    for key, value in envelope.items():
        if key == "catalogSha256":
            continue
        if key == "catalog":
            out["catalogSha256"] = digest
        out[key] = value
    if "catalogSha256" not in out:
        out["catalogSha256"] = digest
    return out


def write_envelope(path: Path, envelope: dict) -> None:
    path.write_text(json.dumps(stamped(envelope), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> None:
    stale = []
    for path in sorted(UI_DIR.glob("*.json")):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("catalogSha256") != catalog_sha256(envelope):
            stale.append(path.name)
            if "--stamp" in sys.argv:
                write_envelope(path, envelope)
    if "--check" in sys.argv and stale:
        raise SystemExit(f"stale catalogSha256 in: {', '.join(stale)} (run python3 scripts/i18n_catalog_identity.py --stamp)")
    print(json.dumps({"status": "ok", "stamped" if "--stamp" in sys.argv else "stale": stale}))


if __name__ == "__main__":
    main()

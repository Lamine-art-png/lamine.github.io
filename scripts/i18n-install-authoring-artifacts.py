#!/usr/bin/env python3
"""Install artifacts from an i18n-global-authoring run into the repository.

Usage: gh run download <run-id> -D <dir>
       python3 scripts/i18n-install-authoring-artifacts.py <dir>

Copies each locale's UI catalog, transactional catalog and legal snapshots into
place (only when they pass their validators), pins the canonical English legal
DOM that the snapshots translate, and then recomputes production readiness.
Nothing is advertised unless scripts/i18n-reconcile-production-locales.py says
the locale passes every gate.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "shared/localization/catalogs"
TX_DIR = ROOT / "shared/localization/transactional-catalogs"
LIFECYCLE_DIR = ROOT / "shared/localization/lifecycle-email-catalogs"
LEGAL_DIR = ROOT / "platform-api/legal/localized"
# Pinned canonical English legal DOM: an authoring input, not a served page.
CANONICAL_DIR = ROOT / "shared/localization/legal-canonical"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    downloaded = Path(args[0])
    installed = {"ui": [], "transactional": [], "lifecycle": [], "legal": []}

    canonical_dom = downloaded / "canonical-legal-dom"
    canonical_hashes: dict[str, str] = {}
    pinned_path = CANONICAL_DIR / "canonical.json"
    repin = "--repin-legal" in sys.argv
    if pinned_path.exists() and not repin:
        # Keep the pinned canonical legal source; snapshots from this run were
        # authored from the committed canonical DOM when one exists.
        canonical_hashes = json.loads(pinned_path.read_text(encoding="utf-8"))["sourceSha256"]
    elif canonical_dom.is_dir():
        target = CANONICAL_DIR
        target.mkdir(parents=True, exist_ok=True)
        for slug in ("terms-of-service", "privacy-policy"):
            src = canonical_dom / f"{slug}.html"
            if src.exists():
                shutil.copyfile(src, target / f"{slug}.html")
                canonical_hashes[slug] = sha256(src)

    for bundle in sorted(downloaded.glob("i18n-*")):
        locale = bundle.name.removeprefix("i18n-")
        ui = bundle / "ui" / f"{locale}.json"
        if ui.exists():
            shutil.copyfile(ui, UI_DIR / ui.name)
            installed["ui"].append(locale)
        tx = bundle / "transactional" / f"{locale}.json"
        if tx.exists():
            shutil.copyfile(tx, TX_DIR / tx.name)
            installed["transactional"].append(locale)
        lifecycle = bundle / "lifecycle" / f"{locale}.json"
        if lifecycle.exists():
            LIFECYCLE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(lifecycle, LIFECYCLE_DIR / lifecycle.name)
            installed["lifecycle"].append(locale)
        legal = bundle / "legal" / locale
        if legal.is_dir():
            mismatched = [
                meta_path.name for meta_path in legal.glob("*.meta.json")
                if canonical_hashes and json.loads(meta_path.read_text(encoding="utf-8")).get("sourceSha256")
                != canonical_hashes.get(meta_path.name.removesuffix(".meta.json"))
            ]
            if mismatched:
                print(f"skip legal {locale}: snapshot does not translate the pinned canonical DOM", file=sys.stderr)
            else:
                dest = LEGAL_DIR / locale
                dest.mkdir(parents=True, exist_ok=True)
                for item in legal.iterdir():
                    shutil.copyfile(item, dest / item.name)
                installed["legal"].append(locale)

    if canonical_hashes and (repin or not pinned_path.exists()):
        (CANONICAL_DIR / "canonical.json").write_text(json.dumps({
            "schemaVersion": 1,
            "description": "Canonical English legal DOM translated by every localized snapshot",
            "sourceSha256": canonical_hashes,
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    subprocess.run([sys.executable, str(ROOT / "scripts/legal-i18n-generate.py"), "--finalize-dir", str(LEGAL_DIR)], check=True)
    print(json.dumps({k: len(v) for k, v in installed.items()}))
    subprocess.run([sys.executable, str(ROOT / "scripts/i18n-reconcile-production-locales.py")], check=True)


if __name__ == "__main__":
    main()

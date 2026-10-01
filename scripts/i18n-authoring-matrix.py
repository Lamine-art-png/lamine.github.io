#!/usr/bin/env python3
"""GitHub output for the authoring matrix: locales the release gate reports as
pending (UI, transactional, legal) plus locales whose lifecycle email catalog
is not current with the English source."""
from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def gate_pending() -> list[str]:
    out = subprocess.run([sys.executable, str(ROOT / "scripts/i18n-reconcile-production-locales.py"), "--pending-matrix"],
                         check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("locales="):
            return json.loads(line.split("=", 1)[1])
    return []


def lifecycle_pending() -> list[str]:
    spec = spec_from_file_location("lifecycle_ready", ROOT / "scripts/i18n-lifecycle-catalog-ready.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((ROOT / "shared/supported-locales.json").read_text(encoding="utf-8"))
    return [code for code in manifest["targetUiLocales"] if code not in {"auto", "en"} and not module.ready(code)]


if __name__ == "__main__":
    pending = gate_pending()
    for code in lifecycle_pending():
        if code not in pending:
            pending.append(code)
    print(f"locales={json.dumps(pending)}")
    print(f"any={'true' if pending else 'false'}")

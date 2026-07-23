from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "figma-enterprise-v4" / "scripts" / "check_ui_literal_inventory.py"
SHARED = ROOT / "shared"

spec = importlib.util.spec_from_file_location("agroai_ui_inventory", CHECKER)
if spec is None or spec.loader is None:
    raise SystemExit("Unable to load UI inventory checker")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

expected: dict[str, str] = module.build_catalog()
parts = sorted(SHARED.glob("ui-literals.en.*.json"))
if not parts:
    raise SystemExit("No literal catalog parts found")

seen: set[str] = set()
removed = 0
for path in parts:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cleaned = {key: value for key, value in payload.items() if key in expected and expected[key] == value}
    removed += len(payload) - len(cleaned)
    overlap = seen.intersection(cleaned)
    if overlap:
        raise SystemExit(f"Duplicate literal keys after reconciliation: {sorted(overlap)[:5]}")
    seen.update(cleaned)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

missing = {key: expected[key] for key in sorted(set(expected) - seen)}
indices = [int(match.group(1)) for path in parts if (match := re.fullmatch(r"ui-literals\.en\.(\d+)\.json", path.name))]
target = SHARED / f"ui-literals.en.{max(indices, default=0) + 1}.json"
target.write_text(json.dumps(missing, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

combined: dict[str, str] = {}
for path in sorted(SHARED.glob("ui-literals.en.*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    overlap = set(combined).intersection(payload)
    if overlap:
        raise SystemExit(f"Duplicate literal keys in final catalog: {sorted(overlap)[:5]}")
    combined.update(payload)
if combined != expected:
    raise SystemExit("Reconciled literal inventory does not match source")

print(f"UI literal inventory reconciled: removed={removed} added={len(missing)} target={target.name}")

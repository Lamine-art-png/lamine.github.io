from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = {"prompt", "chosen", "rejected", "provenance"}


def validate_preferences(path: Path) -> list[dict]:
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        missing = REQUIRED - set(row)
        if missing:
            raise ValueError(f"Preference row {line_no} missing: {sorted(missing)}")
        if not all(str(row[key]).strip() for key in ("prompt", "chosen", "rejected")):
            raise ValueError(f"Preference row {line_no} contains empty prompt/chosen/rejected text")
        if row["chosen"].strip() == row["rejected"].strip():
            raise ValueError(f"Preference row {line_no} has identical chosen and rejected answers")
        provenance = row["provenance"]
        if provenance.get("customer_data") and provenance.get("rights") != "explicit_training_consent":
            raise ValueError(f"Preference row {line_no} uses customer data without explicit training consent")
        if not provenance.get("training_allowed", False):
            raise ValueError(f"Preference row {line_no} is not approved for training")
        if not row.get("expert_reviewed", False):
            raise ValueError(f"Preference row {line_no} must be expert reviewed before DPO")
        rows.append(row)
    if not rows:
        raise ValueError("No preference rows found")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate expert-reviewed Terris preference data.")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    rows = validate_preferences(args.input)
    print(json.dumps({"ok": True, "rows": len(rows), "input": str(args.input)}))


if __name__ == "__main__":
    main()

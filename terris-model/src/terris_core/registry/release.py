from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(root: Path) -> list[dict]:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an immutable Terris Core release manifest.")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--data-manifest", required=True, type=Path)
    parser.add_argument("--eval-report", required=True, type=Path)
    parser.add_argument("--training-config", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if not args.model_dir.exists():
        raise FileNotFoundError(args.model_dir)

    evaluation = json.loads(args.eval_report.read_text(encoding="utf-8"))
    summary = evaluation.get("summary", {})
    if summary.get("critical_pass_rate") != 1:
        raise ValueError("Release blocked: every critical Terris benchmark case must pass.")

    payload = {
        "schema_version": "terris-model-release-v1",
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_files": collect_files(args.model_dir),
        "data_manifest": {
            "path": str(args.data_manifest),
            "sha256": sha256_file(args.data_manifest),
        },
        "eval_report": {
            "path": str(args.eval_report),
            "sha256": sha256_file(args.eval_report),
            "summary": summary,
        },
        "training_config": {
            "path": str(args.training_config),
            "sha256": sha256_file(args.training_config),
        },
        "promotion": {
            "critical_eval_gate_passed": True,
            "production_approved": False,
            "note": "Production approval is a separate human release decision.",
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "version": args.version, "output": str(args.output)}))


if __name__ == "__main__":
    main()

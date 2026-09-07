from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from terris_core.data.schema import TrainingRecord


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_snapshot(dataset: Path, manifest: Path | None, output: Path) -> dict:
    records = [TrainingRecord.model_validate_json(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    domains = sorted({r.domain for r in records})
    languages = sorted({r.language for r in records})
    customer_rows = [r for r in records if r.provenance.customer_data]
    unconsented = [r.id for r in customer_rows if r.provenance.rights != "explicit_training_consent"]
    if unconsented:
        raise ValueError(f"Dataset contains customer rows without explicit training consent: {unconsented[:10]}")
    payload = {
        "schema": "terris.dataset.snapshot.v1",
        "dataset": str(dataset),
        "dataset_sha256": sha256_file(dataset),
        "records": len(records),
        "domains": domains,
        "languages": languages,
        "customer_rows": len(customer_rows),
        "rights_gate_passed": True,
    }
    if manifest and manifest.exists():
        payload["source_manifest"] = str(manifest)
        payload["source_manifest_sha256"] = sha256_file(manifest)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["snapshot_id"] = "terris-dataset-" + hashlib.sha256(canonical).hexdigest()[:16]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an immutable Terris training dataset snapshot.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_snapshot(args.dataset, args.manifest, args.output)))


if __name__ == "__main__":
    main()

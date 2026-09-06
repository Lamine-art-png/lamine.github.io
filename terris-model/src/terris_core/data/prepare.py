from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .schema import TrainingRecord


FORBIDDEN_PRIVATE_MARKERS = (
    "ssn:",
    "social security",
    "api_key=",
    "authorization: bearer",
    "password=",
)


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_records(path: Path) -> list[TrainingRecord]:
    records: list[TrainingRecord] = []
    seen_ids: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        record = TrainingRecord.model_validate(payload)
        if record.id in seen_ids:
            raise ValueError(f"Duplicate record id {record.id!r} on line {line_no}.")
        seen_ids.add(record.id)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for marker in FORBIDDEN_PRIVATE_MARKERS:
            if marker in serialized:
                raise ValueError(f"Potential secret/private marker {marker!r} in record {record.id}.")
        records.append(record)
    if not records:
        raise ValueError("No training records found.")
    return records


def write_prepared(records: list[TrainingRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json(exclude_none=True) + "\n")


def write_manifest(records: list[TrainingRecord], source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    source_text = source.read_text(encoding="utf-8")
    manifest = {
        "schema_version": "terris-training-v1",
        "record_count": len(records),
        "source_sha256": stable_hash(source_text),
        "domains": dict(Counter(record.domain for record in records)),
        "tasks": dict(Counter(record.task_type for record in records)),
        "languages": dict(Counter(record.language for record in records)),
        "rights": dict(Counter(record.provenance.rights for record in records)),
        "customer_records": sum(1 for record in records if record.provenance.customer_data),
        "training_allowed_records": sum(1 for record in records if record.provenance.training_allowed),
        "record_ids_sha256": stable_hash("\n".join(sorted(record.id for record in records))),
    }
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and prepare Terris Core training data.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    records = load_records(args.input)
    write_prepared(records, args.output)
    write_manifest(records, args.input, args.manifest)
    print(json.dumps({"ok": True, "records": len(records), "output": str(args.output), "manifest": str(args.manifest)}))


if __name__ == "__main__":
    main()

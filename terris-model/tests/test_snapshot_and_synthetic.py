import json
from pathlib import Path

from terris_core.data.snapshot import build_snapshot
from terris_core.data.synthetic import build_examples


def test_synthetic_examples_are_governed():
    rows = build_examples(20, 7)
    assert len(rows) == 20
    assert all(row["provenance"]["customer_data"] is False for row in rows)
    assert all(row["expected_tools"] for row in rows)


def test_snapshot_is_content_addressed(tmp_path: Path):
    dataset = tmp_path / "data.jsonl"
    rows = build_examples(3, 2)
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    out = tmp_path / "snapshot.json"
    payload = build_snapshot(dataset, None, out)
    assert payload["snapshot_id"].startswith("terris-dataset-")
    assert payload["rights_gate_passed"] is True


def test_snapshot_rejects_unconsented_customer_data(tmp_path: Path):
    dataset = tmp_path / "bad.jsonl"
    row = build_examples(1, 9)[0]
    row["provenance"]["customer_data"] = True
    row["provenance"]["rights"] = "unknown"
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    try:
        build_snapshot(dataset, None, tmp_path / "out.json")
    except ValueError as exc:
        assert "explicit training consent" in str(exc)
    else:
        raise AssertionError("expected rights gate failure")

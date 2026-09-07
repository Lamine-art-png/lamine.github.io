import json
import tempfile
import unittest
from pathlib import Path

from terris_core.data.snapshot import build_snapshot
from terris_core.data.synthetic import build_examples


class SnapshotAndSyntheticTests(unittest.TestCase):
    def test_synthetic_examples_are_governed(self):
        rows = build_examples(20, 7)
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(row["provenance"]["customer_data"] is False for row in rows))
        self.assertTrue(all(row["expected_tools"] for row in rows))

    def test_snapshot_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "data.jsonl"
            rows = build_examples(3, 2)
            dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            payload = build_snapshot(dataset, None, root / "snapshot.json")
            self.assertTrue(payload["snapshot_id"].startswith("terris-dataset-"))
            self.assertTrue(payload["rights_gate_passed"])

    def test_schema_rejects_unconsented_customer_data(self):
        row = build_examples(1, 9)[0]
        row["provenance"]["customer_data"] = True
        row["provenance"]["rights"] = "agro_ai_owned"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "bad.jsonl"
            dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_snapshot(dataset, None, root / "out.json")


if __name__ == "__main__":
    unittest.main()

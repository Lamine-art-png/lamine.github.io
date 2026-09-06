from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from terris_core.data.prepare import load_records
from terris_core.data.schema import DataProvenance, TrainingRecord


class DataGovernanceTests(unittest.TestCase):
    def test_customer_data_requires_explicit_training_consent(self):
        with self.assertRaises(ValueError):
            DataProvenance(
                source_name="customer export",
                rights="agro_ai_owned",
                customer_data=True,
                training_allowed=True,
            )

    def test_permissive_license_requires_license_id(self):
        with self.assertRaises(ValueError):
            DataProvenance(
                source_name="licensed source",
                rights="permissive_license",
                customer_data=False,
                training_allowed=True,
            )

    def test_valid_owned_record_parses(self):
        record = TrainingRecord.model_validate(
            {
                "id": "record-001",
                "domain": "water",
                "task_type": "reasoning",
                "messages": [
                    {"role": "user", "content": "Do I have enough data?"},
                    {"role": "assistant", "content": "No. Weather is missing."},
                ],
                "provenance": {
                    "source_name": "AGRO-AI synthetic verified scenario",
                    "rights": "agro_ai_owned",
                    "customer_data": False,
                    "training_allowed": True,
                },
            }
        )
        self.assertEqual(record.domain, "water")

    def test_secret_marker_is_rejected(self):
        payload = {
            "id": "record-002",
            "domain": "ops",
            "task_type": "reasoning",
            "messages": [
                {"role": "user", "content": "api_key=secret"},
                {"role": "assistant", "content": "Do not train on secrets."},
            ],
            "provenance": {
                "source_name": "AGRO-AI synthetic verified scenario",
                "rights": "agro_ai_owned",
                "customer_data": False,
                "training_allowed": True,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.jsonl"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path)


if __name__ == "__main__":
    unittest.main()

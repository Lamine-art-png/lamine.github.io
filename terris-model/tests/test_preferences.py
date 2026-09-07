import json
import tempfile
import unittest
from pathlib import Path

from terris_core.data.preferences import validate_preferences


class PreferenceGovernanceTests(unittest.TestCase):
    def _write(self, row):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "prefs.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return tmp, path

    def test_requires_expert_review(self):
        row = {
            "prompt": "What should Terris do?",
            "chosen": "Request the missing weather data.",
            "rejected": "Irrigate 20 mm now.",
            "expert_reviewed": False,
            "provenance": {"customer_data": False, "rights": "agro_ai_owned", "training_allowed": True},
        }
        tmp, path = self._write(row)
        try:
            with self.assertRaises(ValueError):
                validate_preferences(path)
        finally:
            tmp.cleanup()

    def test_accepts_governed_expert_pair(self):
        row = {
            "prompt": "What should Terris do?",
            "chosen": "Request the missing weather data.",
            "rejected": "Irrigate 20 mm now.",
            "expert_reviewed": True,
            "provenance": {"customer_data": False, "rights": "agro_ai_owned", "training_allowed": True},
        }
        tmp, path = self._write(row)
        try:
            self.assertEqual(len(validate_preferences(path)), 1)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()

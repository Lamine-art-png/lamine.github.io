from __future__ import annotations

import argparse
import json
import random
import uuid
from pathlib import Path

TRUTH_LABELS = ["measured", "reported", "calculated", "estimated", "ai_inferred", "unknown"]


def build_examples(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    crops = ["almond", "tomato", "corn", "grape", "potato", "lettuce"]
    languages = ["en", "es", "fr", "pt"]
    examples = []
    for _ in range(count):
        crop = rng.choice(crops)
        language = rng.choice(languages)
        soil = rng.choice(["loam", "clay", "sandy loam", "unknown"])
        weather_age = rng.choice([1, 4, 18, 36])
        label = rng.choice(TRUTH_LABELS)
        has_flow = rng.choice([True, False])
        context = {
            "crop": crop,
            "soil": soil,
            "weather_age_hours": weather_age,
            "soil_moisture_truth": label,
            "flow_measurement_available": has_flow,
        }
        expected = "Use deterministic irrigation and weather tools before giving a numeric schedule. "
        if weather_age >= 24 or soil == "unknown" or label == "unknown":
            expected += "State the missing or stale information and lower confidence."
        else:
            expected += "Preserve the supplied truth labels and explain the result without inventing execution or verification."
        examples.append({
            "id": "synthetic-" + uuid.UUID(int=rng.getrandbits(128)).hex,
            "domain": "water",
            "task_type": "reasoning",
            "language": language,
            "split": "train",
            "messages": [
                {"role": "user", "content": f"Assess irrigation readiness for this {crop} field using this structured context: {json.dumps(context, sort_keys=True)}"},
                {"role": "assistant", "content": expected},
            ],
            "truth_context": context,
            "expected_tools": ["calculate_water_balance", "get_weather"],
            "safety_tags": ["no_fabricated_measurement", "numeric_tool_first", "uncertainty"],
            "provenance": {
                "source": "agro-ai synthetic scenario generator",
                "rights": "agro_ai_owned",
                "license": "proprietary",
                "customer_data": False,
                "training_permission": True,
                "generation_version": "synthetic-v1",
            },
        })
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic Terris synthetic training scenarios.")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1:
        raise ValueError("count must be positive")
    rows = build_examples(args.count, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"ok": True, "records": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()

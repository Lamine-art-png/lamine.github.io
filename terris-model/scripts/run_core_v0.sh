#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DATA_IN="${TERRIS_TRAINING_DATA:-datasets/seed/terris_core_seed.jsonl}"
ARTIFACT_ROOT="${TERRIS_ARTIFACT_ROOT:-artifacts}"
MODEL_DIR="${TERRIS_MODEL_DIR:-$ARTIFACT_ROOT/models/terris-core-v0}"
SERVE_URL="${TERRIS_SERVE_URL:-http://127.0.0.1:8008}"

mkdir -p "$ARTIFACT_ROOT/data" "$ARTIFACT_ROOT/evals" "$ARTIFACT_ROOT/releases"

python -m terris_core.data.prepare \
  --input "$DATA_IN" \
  --output "$ARTIFACT_ROOT/data/terris_core_v0_train.jsonl" \
  --manifest "$ARTIFACT_ROOT/data/terris_core_v0_manifest.json"

python -m terris_core.data.snapshot \
  --dataset "$ARTIFACT_ROOT/data/terris_core_v0_train.jsonl" \
  --manifest "$ARTIFACT_ROOT/data/terris_core_v0_manifest.json" \
  --output "$ARTIFACT_ROOT/data/terris_core_v0_snapshot.json"

python -m terris_core.training.train_lora --config configs/core-v0.json

cat <<EOF
Terris Core training completed.
Next:
  1. Serve the candidate: TERRIS_MODEL_PATH=$MODEL_DIR python -m terris_core.serve.app
  2. Evaluate it: python -m terris_core.evals.run --benchmark evals/benchmark_v0.jsonl --base-url $SERVE_URL --model terris-core-v0 --output $ARTIFACT_ROOT/evals/terris-core-v0.json
  3. Compare against the frozen base model benchmark.
  4. Create a release manifest only after all critical gates pass.
No production traffic is enabled by this script.
EOF

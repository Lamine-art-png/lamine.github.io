# Terris Core Model Platform

Terris Core is AGRO-AI's agriculture-native model program. This directory contains the reproducible path from governed training data to a post-trained model, benchmark results, an inference service, and integration with the existing Terris runtime.

## V0 objective

Terris Core v0 is not a model trained from scratch. It is a proprietary agriculture post-training layer on a permissively licensed open-weight base model. The first target is Qwen3-8B (Apache-2.0) because it is small enough for practical LoRA training and serving while the benchmark remains model-agnostic.

The base model is a dependency. AGRO-AI owns the Terris-specific training corpus, curation rules, post-training recipes, adapters/checkpoints to the extent permitted by the base license, evaluation suite, Field Graph semantics, tool-use behavior, safety policy, and runtime.

## What this platform includes

- governed JSONL training schema with provenance and training-rights checks
- seed agriculture instruction/tool-use dataset
- deterministic dataset validation and preparation
- LoRA supervised fine-tuning pipeline
- benchmark runner with safety, uncertainty, truthfulness, and tool-use checks
- OpenAI-compatible Terris Core inference server
- model card and release gate
- bridge into the existing Terris AI API via LLM_PROVIDER=terris

## Hard rules

1. Never train on customer or field data unless training rights are explicitly recorded.
2. Never convert estimated/inferred values into measured facts.
3. Never invent execution, verification, regulatory approval, sensor readings, satellite observations, yields, or savings.
4. Numeric agronomy remains tool/deterministic-layer first. The language model reasons over validated outputs.
5. Every released checkpoint must have a dataset manifest, benchmark report, model card, and immutable version.
6. Frontier providers remain an optional fallback until Terris Core beats the release gates.

## Local setup

Python 3.11+ and a CUDA-capable GPU are recommended.

Install:

    cd terris-model
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[train,serve]"

Validate and prepare the seed data:

    python -m terris_core.data.prepare \
      --input datasets/seed/terris_core_seed.jsonl \
      --output artifacts/data/terris_core_v0_train.jsonl \
      --manifest artifacts/data/terris_core_v0_manifest.json

Train LoRA:

    python -m terris_core.training.train_lora --config configs/core-v0.json

Serve the adapter:

    TERRIS_MODEL_PATH=artifacts/models/terris-core-v0 \
    python -m terris_core.serve.app

Evaluate:

    python -m terris_core.evals.run \
      --benchmark evals/benchmark_v0.jsonl \
      --base-url http://127.0.0.1:8008 \
      --output artifacts/evals/terris-core-v0.json

## Runtime integration

Set the existing Terris API to:

    LLM_PROVIDER=terris
    TERRIS_CORE_ENABLED=true
    TERRIS_CORE_BASE_URL=http://127.0.0.1:8008
    TERRIS_CORE_MODEL=terris-core-v0

The irrigation agent keeps its current deterministic checks, schema validation, RAG, provenance, and fallback behavior. Terris Core becomes the reasoning provider rather than bypassing those controls.

## Release gate

A model may not be promoted to production just because training completes. It must:

- pass all critical safety scenarios
- produce no fabricated measured values in the benchmark
- preserve missing-data uncertainty
- use the expected tool when the task requires deterministic/external truth
- outperform its unmodified base model on the Terris benchmark
- maintain acceptable latency and cost
- have a completed model card and data-rights manifest

See docs/TERRIS_CORE_MODEL_PLATFORM_V1.md for the end-to-end system design.

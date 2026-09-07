# Terris Core end-to-end V1 status

This branch extends `feat/terris-core-model-platform-v1` without touching production or `main`.

## Built

- governed agriculture training schema and rights gate
- immutable content-addressed dataset snapshots
- deterministic AGRO-AI-owned synthetic scenario generator
- LoRA/QLoRA supervised post-training pipeline
- expert-reviewed preference-data gate and DPO training path
- Terris benchmark runner and critical safety gates
- release registry with model/data/eval/config hashes and base-model comparison gate
- OpenAI-compatible inference service
- typed agriculture operations: reason, recommend, explain, verify
- Terris runtime provider integration, traffic splitting, frontier failover, provenance
- PostgreSQL-backed append-only Field Graph service with tenant-scoped reads and idempotent event ingestion
- training-consent flag and consent-only Field Graph training export
- CI for Python model-platform governance and the existing JavaScript Terris runtime

## Intentionally not claimed as complete

- No Terris Core model weights have been trained in this repository yet; GPU training must run against a selected base checkpoint.
- The seed corpus is a development corpus, not a globally sufficient agricultural training corpus.
- Preference optimization must not run until expert-reviewed pairs exist.
- Vision, realtime speech, global multilingual coverage, equipment-specific tool execution, and regulatory retrieval still require product/data integrations.
- The new Field Graph service requires a provisioned PostgreSQL database and migration before deployment.
- No production deployment, merge, or canary traffic is enabled by this branch.

## Definition of the next real milestone

Terris Core v0 exists only when all of these are true:
1. a legally approved base checkpoint is pinned;
2. a governed dataset snapshot is frozen;
3. LoRA/QLoRA training produces an adapter/checkpoint;
4. the unmodified base and candidate are run on the same frozen benchmark;
5. all critical safety cases pass;
6. the candidate materially beats its base on Terris tasks;
7. a release manifest and model card identify the exact data, config, weights, and eval results;
8. a human explicitly approves any product canary.

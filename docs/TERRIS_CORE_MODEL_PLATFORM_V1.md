# Terris Core Model Platform V1

## Decision

AGRO-AI should build Terris Core now without waiting for a strategic partner. Partners may provide compute, credits, data, or deployment capacity, but the proprietary intelligence stack remains AGRO-AI controlled.

Terris Core V1 is a post-training platform, not a from-scratch foundation-model pretraining program.

## System boundary

Product surfaces:

Terris App / AEP / Field Intelligence / Assurance / Command Center / Platform API / OEM SDK

flow into:

Terris Runtime

which contains:

- planner and tool registry
- deterministic agronomic services
- safety guardrails
- RAG
- verification
- provenance
- Field Graph context
- model router

The model router may call:

- Terris Core
- OpenAI fallback
- Gemini fallback
- local/mock fallback

Terris Core never bypasses deterministic agronomy, Field Graph truth labels, verification rules, or safety controls.

## Proprietary layers

AGRO-AI-owned or AGRO-AI-controlled IP should accumulate in these layers:

1. Field Graph ontology and event history
2. training data curation and provenance
3. synthetic scenario generation and expert-reviewed corrections
4. instruction/tool-use datasets
5. post-training recipes
6. model adapters/checkpoints subject to base-model license
7. agriculture benchmark and red-team suite
8. tool contracts and decision traces
9. safety policies
10. verified recommendation -> decision -> action -> evidence -> outcome data

The last item is the long-run data moat.

## Base model policy

The platform is model-agnostic. V0 defaults to Qwen3-8B because its Apache-2.0 license and size make it practical for independent LoRA experimentation. Before any OEM distribution or commercial release, legal review must re-check the exact base checkpoint license and all incorporated datasets.

A second benchmark candidate should be Ministral 3 8B because it is Apache-2.0 and includes a vision-capable architecture. Do not switch the production base on marketing claims; benchmark both on Terris tasks.

## Data plane

All training examples use a structured record:

- id
- domain
- task_type
- language
- split
- messages
- truth_context
- expected_tools
- safety_tags
- provenance

Provenance contains source, rights, license, customer-data flag, and training permission.

Hard data gate: customer_data=true requires rights=explicit_training_consent.

## Training stages

Stage 0 — baseline
- freeze benchmark
- run unmodified base
- store score and latency

Stage 1 — SFT/LoRA
- truth labels
- missing-data behavior
- tool selection
- field workflow reasoning
- safe explanations
- multilingual agriculture

Stage 2 — tool-use expansion
- structured tool calls
- multi-step plans
- deterministic calculator reliance
- equipment/weather/satellite retrieval

Stage 3 — preference optimization
- collect expert pairwise preferences
- optimize for agronomic usefulness, epistemic humility, and operational clarity
- no preference optimization until preference-data rights and quality are controlled

Stage 4 — broader continued training
- only after the proprietary corpus is large enough to justify additional compute

## Evaluation gates

A checkpoint cannot be promoted if any critical test fails.

Critical families:
- no fabricated measurement
- no fabricated execution
- no fabricated verification
- no unsupported regulatory claims
- no guaranteed yield/savings
- correct uncertainty when key data are missing
- tool-first behavior for numeric/external truth
- provenance awareness
- multilingual safety consistency

Every candidate is compared with:
- current Terris Core production model
- its own unmodified base model
- frontier fallback provider when appropriate

## Serving

The first Terris Core service exposes an OpenAI-compatible /v1/chat/completions boundary. This is deliberate: the existing JavaScript runtime can replace the provider without rewriting decision logic.

Production serving later needs:
- authenticated tenancy
- model version pinning
- batching
- GPU autoscaling
- tracing
- token/cost accounting
- canary traffic
- rollback
- private/OEM deployment
- edge quantization strategy

## Field Graph dependency

Terris Core becomes meaningfully proprietary when it reasons against durable Field Graph context. The current local Field Ledger remains useful for prototyping but is not the final data plane.

Required backend:
- append-only event store
- tenant isolation
- idempotent ingestion
- provenance and truth labels
- object storage for evidence
- vector retrieval
- temporal field state
- training-consent metadata
- de-identification/export/delete controls
- immutable training dataset snapshots

## Voice and multimodal

Realtime voice is a separate transport around the same runtime:

speech input -> transcript/stream -> Terris Runtime -> tools/model -> response tokens -> speech output.

Voice must not become a second intelligence stack.

Images, documents, satellite, telemetry, and geospatial inputs should normalize into Field Graph observations with source/time/truth labels before they affect action state.

## OEM interface

The long-run Terris API should expose typed agricultural primitives rather than only chat:

- reason
- observe
- recommend
- explain
- verify
- field-state
- risk
- vision
- tool-call
- embeddings
- realtime session

OEM customers should be able to pin a Terris Core version, supply their own tools/data, receive provenance, and deploy privately where required.

## Immediate build order

1. freeze Terris V2 as upstream foundation
2. create Terris Core model-platform branch
3. land data schema and rights gate
4. land benchmark v0
5. land LoRA training pipeline
6. land inference service
7. land Terris Core provider in existing API
8. run baseline base-model benchmark
9. grow expert-reviewed agriculture corpus
10. train Core v0
11. compare vs base and frontier fallback
12. only then enable a small canary percentage in product traffic

No production deployment or merge to main is implied by this branch.

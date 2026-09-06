# Terris Core v0 — Model Card Template

Status: development / not approved for production agronomic autonomy

## Intended model

Name: Terris Core v0  
Program owner: AGRO-AI  
Base candidate: Qwen/Qwen3-8B  
Base license: Apache-2.0  
Adaptation: LoRA supervised post-training  
Primary languages in v0: English, Spanish, French seed coverage; broader multilingual coverage requires evaluation before release.

## Intended use

Terris Core v0 is an agriculture reasoning and tool-use model inside the Terris runtime. It is designed to interpret field context, reason over Field Graph facts, explain recommendations, identify missing information, choose tools, preserve truth labels, and support agricultural workflows.

It is not a replacement for deterministic agronomic calculations, sensor measurements, equipment control systems, local labels/regulations, or professional judgment where required.

## Non-goals

- autonomous chemical application
- guaranteed yield or savings claims
- inventing sensor, weather, satellite, or machine observations
- marking recommended/scheduled actions as applied or verified without evidence
- regulatory or legal certification
- unsupervised high-impact equipment actuation

## Data

Every training record must validate against terris_core.data.schema.TrainingRecord. A release must attach the generated dataset manifest. Customer data is forbidden unless explicit training consent is encoded in provenance.

## Required evaluations

- missing-data uncertainty
- truth-label preservation
- no execution/verification fabrication
- no guaranteed yield/savings
- deterministic/tool-first numeric reasoning
- remote-sensing uncertainty
- multilingual safety behavior
- regression against existing Terris irrigation safety harness

## Promotion criteria

Terris Core v0 remains behind a provider flag until all critical benchmark cases pass and it beats the unmodified base model on the Terris benchmark. Production promotion also requires latency/cost targets, observability, rollback, and a signed data-rights review.

## Known limitations

This initial model is text-first. Vision, realtime voice, broad crop/disease knowledge, durable Field Graph memory, and global regulatory coverage are separate workstreams and must not be inferred from the existence of this checkpoint.

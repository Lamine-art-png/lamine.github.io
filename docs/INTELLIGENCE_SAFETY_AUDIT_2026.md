# AGRO-AI Intelligence Safety Audit — August 2026

## Operational paths reviewed

- `/v1/intelligence/recommend` and live variants
- Decision Workbench recommendation/report/export paths
- stable AI and brain fallback routes
- GPT-5.6 evidence graph and structured response path
- agentic controller-action proposal path
- controller request/approval boundary
- DecisionRun, schedule matching, execution verification, and outcome tracking

## P0 finding and remediation

The legacy engine and v0.2 kernel could produce customer-visible irrigation
depth/runtime from fixed multipliers, crop/soil/method lookup tables, an
effective-rainfall fraction, recent-water caps, and default timing. Those values
could flow into recommendations, Workbench reports/exports, tasks, and manual
controller requests.

The production path now delegates to a fail-closed kernel. Legacy calibration
fixtures are marked non-operational and have no import path into the kernel.
No depth, volume, runtime, timing, or irrigation action is emitted until all
required scientific and system inputs are explicit and validated. Results are
proposals requiring human approval; model code has no controller side effect.

## Model and fallback boundary

GPT output is schema-constrained and postvalidated. Evidence text is untrusted
data, not instruction. Invented evidence/rule IDs are removed, unsupported
numeric sentences and recommendations are withheld, recommendations without
evidence or verification are dropped, confidence is capped by grounding, and
physical/external actions are approval-gated. Stable/brain fallback prose passes
the same customer-output sanitizer.

## Remaining production risks

- `DecisionRun`/verification persistence is irrigation-specific and lacks the
  full immutable decision-memory snapshot described in the target architecture.
- Canonical field state is computed per request, not yet a durable time-aware
  state projection with validity intervals and correction history.
- Existing outcome verification policies include domain-specific windows and
  thresholds that require a separately governed calibration review.
- Expert-labelled agronomic truth sets and longitudinal outcome datasets are
  not yet available, so tests prove fail-closed behavior rather than agronomic
  optimality.

Until those P1 items and repository CI are accepted, keep the pull request in
draft and do not deploy or merge it as a complete intelligence-platform release.

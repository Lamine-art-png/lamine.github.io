# AGRO-AI Autonomous Operations Runtime V1

Status: implementation foundation
Date: 2026-09-05
Surfaces: Enterprise Portal, Field Intelligence, Assurance, Command Center, Platform/API execution plane

## Product contract

AGRO-AI owns eligible agricultural work from a trusted trigger to a verified outcome.

The runtime does not turn every model suggestion into an action. Models may classify, reason, or propose. Deterministic procedure and policy state decides whether AGRO-AI can proceed, must request approval, must wait for a physical or external system, or must stop as an exception.

The human is an explicit approval or escalation state rather than the default integration layer between every step.

## One runtime, many agricultural procedures

- Field Issue Resolution — Field Intelligence observation → accountable work → evidence-backed verification → closure.
- Assurance Gap Resolution — deterministic proof gap → evidence collection → review/verification → closure.
- Irrigation Operations — grounded decision → explicit approval → external/controller confirmation → planned-vs-actual verification → closure.
- Harvest Operations — harvest signal/exception → accountable work → verification → closure.
- Finance & Procurement Operations — grounded need → explicit financial approval → external transaction → reconciliation → closure.

These are procedure packs on one substrate. They are not independent products or separate agent stacks.

## Durable state

Migration 032_autonomous_operations adds autonomy_procedures, autonomy_policies, autonomy_runs, autonomy_steps, and autonomy_events.

A run has a stable trigger, procedure version, effective autonomy level, current step, human-decision count, exception count, verification state, outcome state, and timestamps. Every step has an idempotency key and explicit action/risk class.

The event ledger records workflow start, approvals, external execution requests, verification, exceptions, and completion.

## Autonomy levels

| Level | Contract |
| --- | --- |
| A0 | Observe |
| A1 | Recommend |
| A2 | Prepare |
| A3 | Execute with explicit approval |
| A4 | Execute autonomously inside policy |
| A5 | Closed-loop autonomy |

V1 defaults to A4 for safe digital and dispatch work, while high-liability classes remain capped below autonomous execution.

## Non-negotiable safety invariants

1. Model output cannot override deterministic policy.
2. Approval is not execution.
3. Physical, regulated, financial, and destructive actions require explicit human approval in V1.
4. External or physical execution must be separately confirmed before the workflow advances.
5. Execution is not verification.
6. A failed verification becomes an exception; it can never be represented as a successful close.
7. Field Intelligence and Assurance retain their proven primary paths during rolling deployment; autonomy attachment is additive and fail-safe.
8. Customer/organization scope is enforced on every run and step mutation.
9. Workflow actions are idempotent at the step boundary.
10. The Command Center must remain available if autonomy tables are not yet present during a rolling migration.

## Action and risk caps

Default action-class caps: intelligence A4; software A4; field dispatch A4; verification A4; external communication A3; financial A3; regulated A3; physical control A3; destructive A1.

Default risk caps: low A4; medium A4; high A3; critical A2.

The effective level of a step is the lowest of the requested run level, organization/workspace policy, action-class cap, and risk cap.

## Field Intelligence convergence

The existing Field Intelligence operating-loop adapter already creates one durable operator task per observation and preserves observation/evidence/asset provenance.

V1 attaches that task to a field_issue_resolution run. The runtime links the existing task instead of duplicating work, then waits for explicit outcome verification.

This converts capture → observation → task into capture → observation → durable resolution run → accountable task → verification → outcome without weakening the current Field Intelligence path.

## Assurance convergence

The Portal Assurance agent uses authenticated organization/workspace scope and deterministic readiness. When it finds blocking proof gaps, V1 starts an assurance_gap_resolution run.

The runtime may create the evidence-collection task autonomously under A4 because task creation is reversible digital work. It cannot approve evidence, complete human review, certify compliance, file externally, or generate a false readiness state.

## Command Center convergence

The Command Center remains the single initial field-operations request. The existing /v1/field-ops/command-center aggregate now adds an autonomy object instead of introducing another first-paint browser request.

It exposes effective autonomy policy, active workflows, approval queue, external-execution queue, verification queue, exceptions, trailing-30-day Autonomous Completion Rate, verified completion rate, and bounded recent workflow cards.

Operators can approve or reject a gated step, explicitly confirm external execution, or verify/reject an outcome from Command Center. Each action writes durable workflow state and refreshes the existing aggregate.

## Autonomous Completion Rate

Autonomous Completion Rate = eligible workflows completed end-to-end with zero human decisions / all eligible completed workflows.

A field worker carrying out a dispatched physical task does not automatically count as a human decision. An approval, rejection, or judgment gate does.

## Teach AGRO-AI foundation

POST /v1/autonomy/procedures provides the first backend primitive for customer-defined procedures.

A custom procedure is versioned, organization-scoped, validated against the same step/action/risk vocabulary, and must finish with an explicit close step. Updating a procedure creates a new version rather than rewriting operating history.

## Authenticated Portal API

- GET /v1/autonomy/summary
- GET /v1/autonomy/contract
- GET /v1/autonomy/procedures
- POST /v1/autonomy/procedures
- GET /v1/autonomy/runs
- POST /v1/autonomy/runs
- GET /v1/autonomy/runs/{run_id}
- POST /v1/autonomy/runs/{run_id}/steps/{step_id}/approve
- POST /v1/autonomy/runs/{run_id}/steps/{step_id}/reject
- POST /v1/autonomy/runs/{run_id}/steps/{step_id}/complete
- PUT /v1/autonomy/policy

## Next execution layers

1. Provider-specific action adapters with persisted idempotency and receipt IDs.
2. Durable queue/lease execution for long-running procedure steps.
3. Automatic verification adapters for controller telemetry, task evidence, Assurance review events, and machine/work-plan status.
4. Exception recovery and procedure resume.
5. Procedure replay/shadow mode against historical events.
6. Per-procedure economic outcome contracts.
7. Visual Teach AGRO-AI procedure authoring/review.
8. Procedure-template deployment across multi-workspace enterprise accounts.
9. Generalized operational graph entities and event subscriptions.
10. Customer-safe A5 enablement only after procedure-specific evaluation gates pass.

The architecture rule is permanent: new agricultural domains become procedures, tools, policies, and verification adapters on the shared runtime, not disconnected feature silos.
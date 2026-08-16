# Assurance security model

## Authentication, tenancy, and IDOR

Portal endpoints require a verified bearer-authenticated user and canonical workspace membership. The server resolves the Workspace first, derives its Organization, applies the release gate and entitlement gate, and constructs an organization/workspace-scoped repository. Passport IDs, mapping IDs, requirement IDs, source IDs, export IDs, and task provenance are all resolved inside that scope. Cross-organization and cross-workspace IDs return not found.

Historical endpoints preserve verified server-side API keys and the legacy tenant scope. `X-Organization-Id` cannot override the tenant bound to an API key.

## Prompt-injection boundary

Uploaded files, excerpts, field transcripts, observation text, connector payloads, and third-party records are untrusted data. The AGRO-AI system prompt explicitly prohibits treating their text as instructions, self-certifying, bypassing reviews, revealing another tenant, or exposing prompts, credentials, secrets, and private object references. Deterministic readiness and review state are computed in application code, not accepted from model output.

## Evidence and object safety

Assurance maps canonical evidence instead of accepting arbitrary object paths in the Portal workflow. Field media mappings return asset IDs and metadata but not the private object key. Existing object access authorization remains in the owning Evidence/Field Intelligence service.

## Human decision controls

- consequential reviewer decisions are explicit mutations;
- rejection, not-applicable, and additional-proof actions require reasons;
- review history and material events are append-only records;
- mapping corrections are limited to an allowlist and do not alter the source record;
- readiness language never upgrades a mapping into certification or approval.

## Export controls

Exports are workspace scoped, entitlement enforced, immutable, checksummed, versioned, and contain source references plus rule-pack versions. Their posture reports blocked or reviewer-evaluation states. They include the Assurance disclaimer and do not submit to an authority.

## Abuse cases covered by tests

- unauthenticated access;
- cross-organization Workspace and Passport IDs;
- cross-workspace canonical evidence IDs;
- private Field Intelligence object-reference leakage;
- review reason and append-only behavior;
- stale/conflicting evidence scoring;
- export idempotency/versioning;
- evidence-borne prompt injection instructions.

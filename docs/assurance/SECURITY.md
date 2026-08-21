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

Modern Portal exports are cataloged in `GeneratedArtifact` and downloaded only
through the bearer-authenticated Organization/Workspace route. Production bytes
live in the configured R2/S3-compatible store; private object URIs are never
returned to the browser. Production fails closed if durable storage is absent.
The historical API-key endpoint retains inline base64 solely for compatibility.

## Assurance Agent boundary

The modern Agent writes `IntelligenceRun` records in the current Organization
and Workspace identity domain. Its deterministic input contains mapping IDs,
types, statuses, quality/freshness flags, and rule-pack versions. Evidence
titles, excerpts, transcripts, and third-party directives are not instructions
and are not consumed by the triage engine. A run may classify, flag gaps or
conflicts, recommend a task, and prepare a draft-package proposal. It cannot
make review decisions, generate/send a package, certify, file, or execute field
work. Each such action remains a separate authenticated human mutation.

`execution_assurance.py` is not called by V2. Its legacy demo/default-tenant
behavior remains outside the V2 trust boundary.

## Abuse cases covered by tests

- unauthenticated access;
- cross-organization Workspace and Passport IDs;
- cross-workspace canonical evidence IDs;
- private Field Intelligence object-reference leakage;
- review reason and append-only behavior;
- stale/conflicting evidence scoring;
- export idempotency/versioning;
- evidence-borne prompt injection instructions.

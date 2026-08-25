# Assurance V2 requirement certification matrix

This matrix records the requirement-by-requirement forensic disposition for
`feature/aep-assurance-intelligence-v2`. Status describes implemented product
architecture; exact-head test and CI evidence is recorded in the draft pull
request before merge eligibility.

| Requirement | Status | Evidence / disposition |
| --- | --- | --- |
| Bearer-authenticated Organization/Workspace tenancy | COMPLETE | Portal routes resolve `User -> Workspace -> Organization` with `require_workspace_access`; repositories filter every child ID by organization and workspace. |
| Preserve historical `/v1/assurance/*` API-key routes | COMPLETE | Historical router and tenant repository mode remain; inline PDF base64 remains only on this compatibility path. |
| Reuse canonical `EvidenceRecord` | COMPLETE | Portal mappings reference `canonical_evidence_id`; no new portal upload namespace exists. |
| Reuse Field Intelligence observation/media without copying binaries | COMPLETE | Mappings reference `FieldObservation`; responses expose safe asset descriptors and never `object_ref`. |
| Requirement/rule-pack selection and versioning | COMPLETE | Passports select versioned pack IDs; checklist, audit, agent, and package snapshots preserve resolved versions. |
| Water proof | COMPLETE | Generic water scope, measurement, execution, and verification requirements are deterministic; Compliance water records remain scoped adapters. |
| Input proof | COMPLETE | Input application and supporting-record requirements are first-class; historical input APIs remain compatible. |
| Operational-execution proof | COMPLETE | The pack models recommendation -> approval -> task -> execution -> verification without trusting legacy execution routes. |
| Human review and append-only history | COMPLETE | Explicit review actions write `AssuranceReviewEvent` and `AssuranceAuditEvent`; source evidence is not silently rewritten. |
| Explainable deterministic readiness | COMPLETE | Results include requirement states, numerator/denominator/formula, blockers, warnings, pending review, and non-certification meaning. |
| Stale, conflicting, missing, and rejected evidence | COMPLETE | These are explicit states and do not silently contribute usable proof. |
| Missing-proof task creation and provenance | COMPLETE | Explicit user action creates idempotent `field_ops_task` jobs with Passport, requirement, rule-pack, and workspace provenance. |
| Immutable/versioned proof packages | COMPLETE | `AssuranceExport` snapshots are versioned/checksummed and reference immutable `GeneratedArtifact` records. |
| Modern secure package delivery | COMPLETE | Portal APIs return an authenticated download URL; production bytes use existing R2/S3-compatible object storage. Development/test fallback remains server-side in `GeneratedArtifact`, never in the portal JSON response. |
| Historical package delivery compatibility | COMPLETE | API-key export responses retain `content_base64` and legacy language contracts. |
| Modern Assurance Agent workflow | COMPLETE | Bearer-authenticated portal triage writes workspace-scoped `IntelligenceRun` records from server-owned mapping/readiness state. It classifies, detects gaps/conflicts, and proposes explicit next actions/draft packages. |
| Human authority over Agent | COMPLETE | Agent runs cannot accept/reject mappings, generate/send packages, complete review, certify, or execute physical work; proposed actions require a separate human mutation. |
| Prompt-injection isolation | COMPLETE | System prompt and deterministic Agent both treat uploaded evidence as untrusted data; the Agent does not ingest evidence text as instructions. |
| Commercial entitlements | COMPLETE | Readiness, mapping, review, export, and agent capabilities are separately backend-enforced through `commercial_control`. |
| Commercial usage quotas | COMPLETE | Portal Agent runs reserve/commit `agent_run`; modern proof packages reserve/commit `report_export`. Canonical quota reservations carry Organization, Workspace, user, and stable logical request IDs; failure releases and idempotent replay produces one `UsageEvent`. Historical API-key export remains compatible. |
| Fail-closed migration downgrade | COMPLETE | Revision 030 performs a read-only preflight before DDL. Workspace-scoped rows with no legacy tenant and any V2 review/audit history block downgrade with a recovery message; empty and legacy-only PostgreSQL roundtrips remain supported. |
| Localization | COMPLETE | Assurance owns a route-scoped dynamic catalog authorized by the edge canonical-source contract. |
| Assurance-specific route recovery | COMPLETE | Lazy child route has its own error element and cannot replace or redirect the portal shell. |
| Preserve Field Intelligence and existing AEP routes | COMPLETE | Changes are additive to the existing router; Field Intelligence ownership and media delivery remain unchanged. |
| Platform API isolation | COMPLETE | Portal Assurance routes are absent from the public Platform API manifest and service-account surface. |
| Legacy unauthenticated `execution_assurance.py` integration | SUPERSEDED | V2 does not call it. Its demo/default-tenant behavior stays explicitly outside the V2 trust boundary; operational proof uses authorized canonical/Field Intelligence mappings. |
| Historical `customer-portal/` and command-center Assurance UI | SUPERSEDED | `figma-enterprise-v4` is authoritative; obsolete surfaces are not restored. |
| Autonomous compliance/certification decisions | SUPERSEDED | Explicitly excluded in favor of deterministic readiness plus authoritative human review. |

## Remaining limitations

- Generic rule packs organize evidence readiness; they are not jurisdictional
  legal opinions or certification-program determinations.
- Production package generation fails closed when the configured durable object
  store is unavailable. The database fallback exists only outside
  production/staging for tests and local development.
- Assurance does not submit filings, send packages externally, activate a live
  connector, or perform physical agricultural actions.
- The historical execution-assurance router still contains legacy behavior; it
  is not a V2 dependency and should be hardened independently before any future
  integration.

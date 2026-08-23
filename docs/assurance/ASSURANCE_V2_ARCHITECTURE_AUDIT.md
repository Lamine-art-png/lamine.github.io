# Assurance V2 architecture audit

Date: 2026-08-16

Baseline: `origin/main` at `04592b49ef8e291476b85797e1fdf3f7e39d2996`

## Mandatory current-main audit

| Item | Current truth |
| --- | --- |
| Repository | `/Users/laminedabo/Documents/GitHub` |
| Isolated worktree | `/Users/laminedabo/Documents/Codex/worktrees/aep-assurance-intelligence-v2` |
| Feature branch | `feature/aep-assurance-intelligence-v2` |
| Feature HEAD before changes | `04592b49ef8e291476b85797e1fdf3f7e39d2996` |
| `origin/main` | `04592b49ef8e291476b85797e1fdf3f7e39d2996` |
| Primary worktree state | Clean, but 1,015 commits behind fetched `origin/main`; it was not modified |
| Isolated worktree state | Clean at audit time |
| Alembic head | `029_platform_cli_device_auth` (exactly one head) |
| Portal owner | `figma-enterprise-v4/`; Vite/React Router, deployed by `.github/workflows/deploy.yml` to the authoritative Cloudflare Pages project |
| Backend route owner | `agroai_api/app/main.py`; FastAPI owns authenticated `/v1/*` routes behind the current API edge |
| Recovery artifact | Verified complete Git bundle at `outputs/recovery/agro-ai-pre-assurance-20260816.bundle` in the task deliverables directory |

## Historical recovery findings

The requested PR heads were fetched and inspected directly as `origin/pr-52`, `origin/pr-54`, `origin/pr-57`, `origin/pr-60`, `origin/pr-65`, `origin/pr-66`, and `origin/pr-67`.

| Historical work | Disposition |
| --- | --- |
| PR #52 California compliance pack | Reusable persistence and water-readiness lineage. Its old customer-portal screen is obsolete. |
| PR #54 expanded compliance integration | Superseded by the hardened PR #57/#60 lineage; useful only as historical design evidence. |
| PR #57 compliance hardening | Reusable tenant-scoped repository, deterministic evaluation, and migration-safety ideas. The separate command-center and legacy portal surfaces are obsolete. |
| PR #60 global Compliance kernel | Present on current main. Preserve data and routes; use it as a legacy water-readiness adapter rather than the customer-facing product name. |
| PR #65 Assurance Audit MVP | Present on current main. Preserve Passport, input, limited traceability, rule-pack identifiers, and historical endpoints. Modernize its evidence rows into mappings to canonical evidence instead of making them a second upload store. |
| PR #66 Assurance agent workflow | Present on current main. Reuse deterministic triage and human-approval semantics; add an explicit untrusted-evidence boundary and portal-authenticated workspace scope. |
| PR #67 Enterprise OS portal | Its concepts informed the current portal, but `customer-portal/` is no longer authoritative. Do not restore it. |

## Current reusable systems

### Identity, tenancy, and authorization

`app.api.deps.AuthContext`, `get_auth_context`, and `require_workspace_access` are authoritative for portal users. They enforce active users, credential freshness, verified email, organization membership, organization approval, suspended-account restrictions, and workspace ownership. Browser-supplied organization IDs are not authoritative.

Historical Assurance routes use verified server-side API keys associated with the legacy `tenants` domain. They must remain compatible, but new portal routes must use the current `organizations` and `workspaces` identity domain.

### Canonical evidence

`app.models.operational_records.EvidenceRecord` is the canonical normalized operational evidence record. It already carries organization (`tenant_id`), workspace, source/connector references, type, field/block scope, occurrence/source timestamps, title, summary, value, confidence, quality, citation, source excerpt, and metadata.

`DataSource` owns uploaded-object references and checksums. `FieldObservation` owns durable Field Intelligence truth, extraction confidence, corrections, provenance, task/evidence IDs, and audit history. `FieldObservationAsset` owns only authorized object-storage references and checksums; media binaries remain in the existing R2-compatible store. Assurance should reference these records by ID and never copy their media.

The following are legacy or domain-specific adapters, not competing canonical evidence stores:

- `ComplianceEvidence` and Compliance measurements/budgets: historical readiness inputs;
- `AssuranceEvidenceArtifact`: currently duplicates evidence metadata, and must become a compatibility mapping row with canonical source references;
- Workbench artifacts: uploaded-analysis session records that may map to canonical/Assurance evidence but do not own a new upload namespace.

### Reports and exports

The portal report factory and `app.api.v1.chat_artifacts.build_report_pdf_bytes` provide the current server-side branded PDF infrastructure. `GeneratedArtifact` is the modern artifact catalog. Assurance packages should reuse the renderer and persist immutable package snapshots/version metadata in the historical `assurance_exports` table, without silently modifying prior packages.

### Field Intelligence provenance

The authoritative workflow is Capture -> Understand -> Decide -> Act -> Verify. `FieldCaptureSession`, `FieldObservation`, `FieldObservationAsset`, `FieldObservationProcessingRun`, and append-only `FieldObservationAuditEvent` preserve capture, media custody, extraction/model provenance, corrections, task links, and verification context. Assurance V2 should expose eligible observations as referenceable candidates, preserving the original record and object reference.

### Agents

`app.agents.orchestrator.AgentOrchestrator` provides deterministic Assurance triage, grounded proposed actions, truth constraints, and human-approval flags. The general AI routes use the model router but currently need stronger language that uploaded evidence is untrusted data, never instruction. Deterministic rule-pack evaluation remains authoritative.

### Commercial control plane

`app.services.commercial_control` is authoritative for plan capabilities, contracts, subscription state, overrides, and quotas. Historical plan aliases (`assurance_audit`, `assurance`) already map to current Professional/Team plans; no Stripe products or prices should be created. Add granular Assurance capabilities to this existing map and keep backend checks authoritative.

### Localization

The authoritative portal uses core catalogs, deterministic static literal inventory, and route-scoped dynamic catalogs through `usePortalCopy`. Assurance copy should receive its own route-scoped dynamic catalog. Customer names and evidence free text remain data and must not be translated as UI chrome.

### Rollout and route isolation

React Router lazy-loads operation routes, and `MainLayout` owns the persistent shell. Assurance already has a lazy route, but it lacks its own child error element. V2 must add an Assurance-specific child recovery boundary so a chunk or render failure stays inside the outlet. Server-side release state should default disabled/internal in production and may be general only in development or by explicit configured rollout.

## Duplicate and obsolete domains

- `customer-portal/` and `apps/agroai-command-center-v2/` are historical/non-authoritative customer surfaces.
- `/v1/workspaces/{workspace_id}/assurance/overview` currently returns synthetic percentages and must be replaced with live deterministic data.
- `figma-enterprise-v4` currently calls `/v1/assurance/readiness` and `/v1/assurance/passport`, routes that do not exist. This is a thin placeholder rather than a working Assurance product.
- `AssuranceEvidenceArtifact` currently stores file references and copied descriptive fields. V2 will preserve the table/API but prefer foreign-key/source references to `EvidenceRecord`, Field Intelligence observations, Compliance evidence, or Workbench artifacts.
- The historical Compliance product name and California-specific portal are not the new customer IA. California groundwater logic may survive only as clearly labeled reporting-readiness logic.
- Inline base64 PDF payloads are historical compatibility behavior, not the preferred future object-storage delivery mechanism.

## Additive implementation decision

1. Preserve historical `/v1/assurance` API-key endpoints and identifiers.
2. Add portal-authenticated, workspace-scoped Assurance routes without adding them to the public Platform API manifest.
3. Extend the existing Assurance schema additively from the real Alembic head; preserve all historical Assurance/Compliance rows.
4. Treat `AssuranceEvidenceArtifact` as the Passport-to-source mapping/assessment record. Prefer `EvidenceRecord` and Field Intelligence references; keep legacy file fields for old rows.
5. Add append-only review and audit events, versioned package metadata, clear evidence status, and explainable deterministic readiness.
6. Add first-class `water_assurance_generic_v1`, `buyer_input_records_v1`, and `operational_execution_proof_v1` packs while retaining all historical IDs as supported packs/aliases.
7. Reuse existing task jobs for Assurance next actions and the existing branded server-side report builder for packages.
8. Add a native, localized, route-isolated Assurance workbench in `figma-enterprise-v4`.

## Out of scope

Assurance V2 does not certify, determine legal compliance, file with regulators, replace the ERP/warehouse stack, expand the public Platform API, create Stripe products, duplicate object storage, perform physical actions, deploy production, or activate the feature for general production access.

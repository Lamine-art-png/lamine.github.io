# Assurance V2 architecture

## Placement in the current product

The authoritative portal is `figma-enterprise-v4`. Its `/assurance` child route is lazy-loaded under `MainLayout`. The route owns an `AssuranceRouteRecovery` error element, so a failed Assurance chunk or render leaves the sidebar, status bar, workspace selector, and all sibling routes intact.

The authoritative backend route registry is `agroai_api/app/main.py`. Portal endpoints are registered from `app.api.v1.assurance.portal_router`. The earlier API-key endpoints remain registered from the same module for backward compatibility. The formerly synthetic SaaS overview endpoint now delegates to the real repository.

## Domain boundary

`AssuranceRepository` has two explicit construction modes:

- legacy: `tenant_id`, for historical API keys and the old `tenants` domain;
- portal: `organization_id`, `workspace_id`, and actor user, for current bearer-authenticated customers.

Exactly one mode is accepted. Every Passport lookup and child query is filtered through that mode before an ID is resolved. This prevents IDOR and avoids an unsafe cross-domain foreign-key migration.

## Main records

- `AssurancePassport`: selected scope, entity, period, rule packs, and current readiness posture.
- `AssuranceChecklistItem`: deterministic requirement instance with blocking and review semantics.
- `AssuranceEvidenceArtifact`: a mapping from a Passport to a canonical source, retained under its historical table name.
- `AssuranceReviewEvent`: append-only human review decision.
- `AssuranceAuditEvent`: append-only material-event and provenance ledger.
- `AssuranceExport`: immutable, versioned package snapshot.

## Deterministic readiness

Readiness is recomputed from selected checklist items, scoped evidence mappings, explicit review state, source freshness, unresolved conflicts, and supported scoped Compliance assets. The response explains numerator, denominator, blocking issues, warnings, pending review, and what the score does not mean.

States include `missing`, `present`, `unreviewed`, `mapped`, `reviewer_required`, `stale`, `conflicting`, `rejected`, `accepted`, and `not_applicable`. A package can be `blocked`, `reviewer_evaluation_required`, or `ready_for_reviewer_evaluation`; none is a certification state.

## Reused infrastructure

- Authentication: `get_current_user` and `require_workspace_access`.
- Commercial enforcement: `commercial_control.require_feature`.
- Canonical evidence: `EvidenceRecord` and `DataSource`.
- Field proof: `FieldObservation` and `FieldObservationAsset` references.
- Field actions: durable `IngestionJob` with `job_type=field_ops_task`.
- PDF output: the current branded `build_report_pdf_bytes` engine.
- Localization: route-scoped `usePortalCopy` and edge-authorized canonical source catalogs.

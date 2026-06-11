# Terris Field Ledger

The Terris Field Ledger is the shared field-level operating record. It prevents duplicated water, nutrient, energy, task, and proof logs from drifting apart.

## Event Envelope

The canonical event is implemented in `apps/velia-mobile/js/domain/fieldLedger.js` as `createTerrisFieldEvent`.

Core fields:
- organization, workspace, farm, field, block, and crop-cycle identifiers
- event type and module key
- occurred and recorded timestamps
- source mode and source record ID
- truth label, confidence, data quality, provenance, payload, attachments, and limitations

## Event Taxonomy

Implemented event types include:
- irrigation recommendation, approval, schedule, applied, verified
- fertigation plan and applied
- nutrient application
- pumping runtime and cost estimate
- field observation
- anomaly detected
- crop-protection task boundary
- task created and completed
- evidence attached and evidence packet generated
- outcome recorded

## Truth Labels

Truth labels distinguish measured, reported, calculated, estimated, AI-inferred, and unknown values. Terris does not treat those as interchangeable.

## Provenance

Provenance records the source, actor context where available, source timestamp, assumptions, and limitations. Demo records are labeled as representative demo data.

## Module Reuse

Water recommendations, manual irrigation logs, field observations, nutrient records, pump runtime estimates, field tasks, and evidence packets all enter the same ledger. Proof packets reuse existing ledger events instead of creating a parallel report-only history.

## Implemented Versus Staged

Implemented now:
- in-memory/local mobile ledger events
- water adapter events for recommendations, applied water, and observations
- beta event helpers for nutrients, energy, ops, and proof
- tests for truth labels and state separation

Staged:
- backend ledger persistence
- tenant-scoped database migrations
- Protect event expansion
- Risk API portfolio contracts

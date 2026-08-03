# Terris Field Ledger

The Terris Field Ledger records operational field events in a canonical local event envelope. It is a local mobile buffer only, not a durable audit archive.

## Envelope

Supported fields include `id`, `organizationId`, `workspaceId`, `farmId`, `fieldId`, `blockId`, `cropCycleId`, `eventType`, `module`, `occurredAt`, `recordedAt`, `sourceMode`, `sourceSystem`, `sourceRecordId`, `truthLabel`, `confidence`, `dataQuality`, `provenance`, `payload`, `attachments`, and `limitations`.

Local metadata is explicit:

- `retentionLimit`
- `persistenceMode: "local_mobile_buffer"`
- `durableBackendPersistence: false`
- `queuedForSync`

## Taxonomy

Truth labels are canonical machine slugs: `measured`, `reported`, `calculated`, `estimated`, `ai_inferred`, `unknown`.

Unsupported modules, event types, source modes, truth labels, and data quality labels are rejected explicitly.

## Render Safety

Render and recommendation display paths do not append events, mutate state, or persist state. Water recommendation events are written only from concrete state transitions such as materially new backend decisions. Irrigation and observation events are written when users save those records.

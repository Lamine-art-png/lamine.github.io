# Terris Product Architecture

Terris Foundation V2 is a local-first mobile foundation layered onto the latest mobile intelligence base. The physical compatibility directories remain `apps/velia-mobile` and `apps/velia-ai-api`; user-facing product copy is Terris.

## Boundary

- Mobile state is a local browser buffer, not a durable audit archive.
- Field Ledger events are retained locally with `persistenceMode: "local_mobile_buffer"` and `durableBackendPersistence: false`.
- Backend Terris aliases are configuration-only in this phase. No backend ledger persistence, migrations, or public Terris ledger API were added.
- Water behavior remains the active production module. Nutrients, Energy, Ops, and Proof are beta surfaces. Protect is preview-only. Risk API is reserved documentation only.

## Modules

- Terris Water: active by default.
- Terris Nutrients: beta, disabled by default in real mode.
- Terris Energy: beta, disabled by default in real mode.
- Terris Ops: beta, disabled by default in real mode.
- Terris Proof: beta, disabled by default in real mode.
- Terris Protect: preview, disabled unless explicitly enabled for controlled development.
- Terris Risk API: reserved, disabled unless explicitly enabled for controlled development.

## Next Phase

The next phase should add durable backend Field Ledger persistence, server-side sync contracts, tenant isolation, retention policies, export controls, and migration scripts. This pass intentionally avoids backend schema changes.

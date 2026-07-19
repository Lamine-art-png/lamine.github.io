# Platform API rollback runbook

Disable only the flags for the affected stage. Do not delete projects, keys,
applications, usage, subscriptions, outboxes, support requests, or incidents.
Stop new Checkout/meter export before changing billing integrations; durable
rows remain available for reconciliation.

If code rollback is required, use the normal reviewed release rollback and a
schema version supported by the downgrade notes. Migrations are additive; do
not downgrade after customer rows exist without a data-retention decision.
Confirm Platform API routes return the launch-contract 404 while Enterprise
Portal auth, billing, uploads, Queue, outbox, R2, and core workflows remain
healthy.

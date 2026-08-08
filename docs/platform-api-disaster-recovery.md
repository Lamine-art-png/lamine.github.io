# Platform API disaster recovery standard

Status: required operating standard; targets remain unproven until exercised.

## Recovery targets

The initial target is RPO no greater than 15 minutes and RTO no greater than four hours for the Platform API system of record. Stripe remains the payment system of record. Redis is reconstructible coordination state and must never be the only copy of customer or billing truth. Object-storage recovery depends on bucket versioning, retention, and provider durability settings.

## Required controls

- PostgreSQL automated backups and point-in-time recovery with a documented retention window.
- A quarterly restore into an isolated environment, including Alembic version proof, tenant-isolation checks, and sampled row/count reconciliation.
- Object-store versioning and lifecycle review plus checksum-based recovery proof.
- Stripe subscription, invoice, webhook-event, and usage-meter reconciliation.
- Exact-SHA application and edge rollback with immutable evidence.
- A dependency map and named recovery owner for database, API, edge, queue, object storage, authentication, billing, and provider integrations.

## Exercise evidence

A drill is complete only when it records start and end time, selected restore point, data-loss window, achieved RPO and RTO, schema SHA, application SHA, reconciliation results, failures, remediation owner, and deadline. Documentation alone is not a successful restore test.

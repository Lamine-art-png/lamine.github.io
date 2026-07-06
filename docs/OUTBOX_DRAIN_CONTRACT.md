# Connector outbox drain contract

Connector task publication uses the transactional task outbox as the durable recovery boundary.

Release invariant:

- only pending outbox rows are eligible for publication
- successful publication changes the row to published with a published timestamp
- failed publication increments the attempt counter and schedules a bounded retry
- a second drain pass must not republish a row that is no longer pending
- Queue delivery itself remains at-least-once, so connector job processing must stay idempotent by job state and lease ownership

The Cloudflare Queue path intentionally treats non-terminal backend states as retryable. Terminal job states are acknowledged; transient job states are retried by the Queue policy.

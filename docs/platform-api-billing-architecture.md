# Platform API billing architecture

API billing is separate from existing Enterprise Portal billing. An organization
may hold either subscription, both, or an enterprise combined contract.

The internal PostgreSQL usage ledger is authoritative for authorization, credit
reservation, quota, overage eligibility, and dashboards. Stripe settles
subscriptions and asynchronous overages; a Stripe meter summary never gates a
request.

Logical flow:

1. lock the active subscription and reserve versioned operation credits;
2. execute or enqueue the customer operation once under idempotency;
3. commit or release the reservation;
4. create one usage event;
5. create one uniquely identified Stripe meter-outbox row when eligible;
6. Queue exports with bounded backoff and terminal failure;
7. reconciliation marks exported records only after Stripe processing evidence.

States are `free`, `trialing`, `active`, `past_due`, `grace`, `unpaid`,
`canceled`, `suspended`, and `enterprise_contract`. Payment failure enters a
configurable grace period; data is not automatically deleted.

# ADR 007: internal credits authorize; Stripe settles

Accepted.

PostgreSQL credit reservations and usage events authorize requests. Stripe
Billing Meters receive asynchronous, idempotent exports for settlement.
Authorization cannot depend on eventually consistent Stripe summaries.

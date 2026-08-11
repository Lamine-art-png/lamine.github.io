# Platform API metering runbook

Monitor reservations by state, usage-event uniqueness, meter-outbox age,
attempts, terminal failures, and reconciliation lag. An internal retry must reuse
the logical operation ID and cannot reserve or meter again.

Recovery:

1. leave export disabled if Stripe configuration is incomplete;
2. inspect terminal errors without logging payloads or secrets;
3. repair the customer/subscription mapping;
4. requeue the exact outbox ID;
5. use its stable meter-event identifier;
6. reconcile against Stripe test-mode processing;
7. audit any backfill range and outcome.

Never infer successful reconciliation from enqueue or API acceptance alone.

# Platform API incident-response standard

## Severity

- **SEV-1:** confirmed cross-tenant exposure, active credential compromise, unauthorized physical-action risk, or broad production outage.
- **SEV-2:** material degradation, billing corruption risk, lost asynchronous custody, or a security event with bounded impact.
- **SEV-3:** limited customer impact with a workaround.

## Response contract

For SEV-1, disable the affected capability first, preserve evidence, revoke or rotate impacted credentials, and name an incident commander. Use the status system for truthful customer updates. Do not speculate about cause or impact. Maintain an event timeline using UTC, release SHAs, request IDs, organization IDs, audit-event IDs, Stripe event IDs, queue and outbox identifiers, and operator actions without copying secrets or customer payloads.

## Required closure

A resolved incident requires impact and affected-customer determination, containment, recovery verification, root cause, contributing conditions, corrective actions with owners and dates, customer communication decision, and a blameless postmortem. SEV-1 and SEV-2 corrective actions remain tracked until verified, not merely merged.

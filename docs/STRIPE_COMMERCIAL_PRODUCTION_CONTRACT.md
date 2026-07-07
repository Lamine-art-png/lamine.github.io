# AGRO-AI Stripe Commercial Production Contract

This document is the operational contract for the self-serve AGRO-AI money engine.
Production readiness and public edge cutover fail closed when the required core
Stripe configuration is incomplete.

## Required backend configuration

The API runtime must provide:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_PRO_MONTHLY`
- `STRIPE_PRICE_PRO_ANNUAL`
- `STRIPE_PRICE_TEAM_MONTHLY`
- `STRIPE_PRICE_TEAM_ANNUAL`
- `STRIPE_PRICE_NETWORK_MONTHLY`
- `STRIPE_PRICE_NETWORK_ANNUAL`

The six self-serve offer values must be distinct Stripe Price IDs beginning with
`price_`. Reusing one Price ID for multiple monthly/annual offers is a production
blocker because it makes offer reconciliation ambiguous.

The following one-time service prices are optional for core SaaS readiness:

- `STRIPE_PRICE_ASSURANCE_AUDIT_FARM`
- `STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK`

If configured, those offers remain one-time services and must not grant a SaaS
plan.

## Authoritative subscription state

`checkout.session.completed` is not subscription activation.

Runtime access follows the Stripe subscription lifecycle:

- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

One-time payment success and invoice success do not independently upgrade a SaaS
plan. Inactive paid subscriptions are restricted to Free-equivalent runtime
capabilities until an authoritative active/trialing/contracted state is restored.

## Webhook ownership

The established live endpoint is:

`https://api.agroai-pilot.com/v1/billing/webhook`

`api.agroai-pilot.com/v1/*` is owned by the Cloudflare Worker
`agroai-api-edge`, which proxies to the private upstream runtime. The Worker route
must remain present alongside the authenticated portal route.

Webhook requests are verified server-side with `STRIPE_WEBHOOK_SECRET`. Do not
send browser traffic, API keys, Queue tokens, or signing secrets to the portal
bundle.

## Release acceptance

A production release is not complete until all of the following are true for the
same Git SHA:

1. the backend release contract reports the exact runtime build SHA;
2. Alembic database and repository heads match;
3. durable Queue configuration is ready;
4. durable object storage is configured and reachable;
5. global production readiness has zero blockers, including the Stripe contract;
6. the Cloudflare edge deploy succeeds with exact Queue secrets;
7. public edge and upstream smoke checks pass;
8. the enterprise portal deploy and production smoke pass;
9. immutable release evidence is recorded.

Do not bypass the exact-SHA wait by weakening the release workflow. A backend
source/configuration contract change should be merged when a new backend build is
required; workflow-only commits may not cause the upstream provider to publish a
new runtime SHA.

## Incident rule

If Stripe reports delivery failures, first distinguish:

- application/webhook rejection;
- public edge/DNS reachability;
- upstream timeout;
- exact backend release lag.

Do not rotate Stripe secrets merely to repair routing. Preserve the existing
endpoint when possible, restore its route through the validated edge, then prove
reachability and signed delivery through production evidence.

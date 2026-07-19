# Platform API Stripe runbook

All API-billing flags default false. Development uses Stripe test mode only.

Required before test activation:

- purpose-separated `PLATFORM_API_STRIPE_SECRET_KEY`;
- API-billing webhook endpoint and
  `PLATFORM_API_STRIPE_WEBHOOK_SECRET`;
- Developer/Scale monthly, annual, and overage price IDs;
- Billing Meter ID and event name;
- reviewed Customer Portal configuration;
- active database catalog version matching configured prices.

Use the test provisioning script in dry-run mode first. It must reject `sk_live`
unless an explicit live-operator confirmation is supplied. This repository
change does not create Stripe resources.

Checkout looks up plan and price server-side, reuses the organization Stripe
customer, creates one API subscription slot, and includes organization and API
subscription metadata. The dedicated webhook verifies signatures, deduplicates
event IDs, rejects cross-organization mapping, and ignores older state events.

Optional Stripe Tax is disabled by default. Enabling it requires reviewed tax
codes, address collection, customer-address behavior, and tax readiness.

# AGRO-AI Platform API Stripe activation

This runbook activates the purpose-separated Platform API billing system. It does not alter Enterprise Portal plans or subscriptions.

## Approved catalog

| Plan | Monthly | Annual | Included credits | Additional usage |
|---|---:|---:|---:|---:|
| Developer | $149 | $1,430 | 250,000 | $0.75 per 1,000 credits |
| Scale | $749 | $7,190 | 2,000,000 | $0.35 per 1,000 credits |

The repository catalog identifier remains `2026-07-provisional`. Activation therefore requires an explicit approval input and an auditable reason. Pricing changes require a new catalog version and new immutable Stripe Prices.

## What the workflow provisions

The `Platform API Stripe Activation` workflow creates or safely reuses:

- one Stripe Product for Developer;
- one Stripe Product for Scale;
- monthly and annual recurring Prices for both plans;
- one Stripe Billing Meter named `agroai_api_credits`;
- one metered overage Price for each plan;
- one Platform API Customer Portal configuration;
- one signed Platform API webhook endpoint;
- the corresponding Render environment configuration;
- the active database catalog state;
- a redacted production evidence artifact.

Payment credentials remain on Stripe-hosted Checkout. The browser receives only a short-lived Checkout URL or Customer Portal URL.

## Required protected secrets

### Production environment

- `PLATFORM_API_STRIPE_LIVE_SECRET_KEY`
- `RENDER_API_KEY`
- `PRODUCTION_API_SERVICE_ID`
- `PLATFORM_API_ADMIN_BEARER_TOKEN`
- `PLATFORM_API_BILLING_SMOKE_BEARER_TOKEN`

The admin token must belong to a current Platform administrator. The billing smoke token must belong to a verified internal organization with an active Platform API enrollment and no existing paid API subscription.

### Staging environment

- `PLATFORM_API_STRIPE_TEST_SECRET_KEY`
- `RENDER_API_KEY`
- `STAGING_API_SERVICE_ID`
- `STAGING_API_URL`
- `STAGING_PLATFORM_API_ADMIN_BEARER_TOKEN`
- `STAGING_PLATFORM_API_BILLING_SMOKE_BEARER_TOKEN`

Never place Stripe secrets, webhook signing secrets, or bearer tokens in repository variables, workflow inputs, artifacts, comments, or screenshots.

## Activation order

### 1. Validate in Stripe test mode

Run `Platform API Stripe Activation` with:

- mode: `test`
- action: `provision`
- configure Render: enabled
- deploy: enabled
- activate catalog: enabled
- prove Checkout: enabled
- confirmation: `PROVISION AND ACTIVATE AGROAI PLATFORM TEST BILLING`

The workflow must prove the pricing response and create a valid Stripe-hosted Checkout session for the internal smoke organization. Complete the test Checkout with a Stripe test card, then confirm:

- the webhook marks the API subscription active;
- the customer can open the Stripe Customer Portal;
- an API request creates durable usage;
- the meter outbox exports exactly once;
- the Stripe meter summary reflects the usage event;
- cancellation and payment-failure states reconcile correctly.

### 2. Activate live mode

Run the same workflow with:

- mode: `live`
- action: `provision`
- configure Render: enabled
- deploy: enabled
- activate catalog: enabled
- prove Checkout: enabled
- confirmation: `PROVISION AND ACTIVATE AGROAI PLATFORM LIVE BILLING`

The protected `production` environment must require approval. Review the workflow summary and redacted artifact before approving the job.

### 3. Complete one controlled real purchase

Use an AGRO-AI-owned internal organization. Complete one Developer monthly purchase with a company card. Confirm all of the following before inviting an external customer:

- Checkout displays the correct plan and price;
- the successful payment returns to Platform API Billing;
- the webhook changes the local subscription to `active`;
- the Stripe invoice and receipt are correct;
- the Customer Portal opens and shows the invoice;
- included credits and overage terms match the approved catalog;
- no Enterprise Portal subscription was changed;
- no duplicate customer, subscription, invoice, or meter event was created.

Cancel the internal subscription at period end after the proof unless it will remain the permanent billing smoke account.

## Customer experience

Approved Platform developers open:

- standalone: `https://platform.agroai-pilot.com/billing`
- Enterprise Portal: `https://app.agroai-pilot.com/platform/billing`

The page shows the official AGRO-AI identity, monthly and annual plan pricing, included credits, metered overage rates, secure Checkout, current subscription state, renewal date, usage access, and the Stripe Customer Portal.

## Rollback

Rollback must stop new purchases without corrupting existing Stripe subscriptions.

1. Set `PLATFORM_API_STRIPE_CHECKOUT_ENABLED=false`.
2. Set `PLATFORM_API_PRICING_ENABLED=false` when public pricing must be hidden.
3. Leave `PLATFORM_API_BILLING_ENABLED=true` while existing webhook events and subscription state still need reconciliation.
4. Leave `PLATFORM_API_STRIPE_METER_EXPORT_ENABLED=true` until all already-recorded billable usage has been exported or explicitly waived.
5. Deactivate the database catalog through the Platform admin endpoint only after Checkout is closed.
6. Do not delete Stripe Products, Prices, Customers, Subscriptions, invoices, meter events, or webhook history.
7. Record the incident, affected organizations, financial exposure, and reconciliation decision.

## Safety properties

- Stripe key mode must match the selected workflow mode.
- Live mutation requires exact confirmation.
- Stripe Prices are immutable and server-controlled.
- Browser-supplied Price IDs are rejected.
- Checkout creation is organization-scoped and idempotent.
- Stripe webhook signatures and live/test mode are verified.
- Duplicate and out-of-order webhook events cannot regress subscription state.
- Usage exports use durable outbox identifiers and cannot be exported twice.
- Render mutation is restricted to the Platform API billing allowlist.
- Secret files use mode `0600` and are deleted before artifact upload.
- The workflow publishes only redacted evidence.

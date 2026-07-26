# AGRO-AI Platform API Stripe activation

This runbook activates the purpose-separated Platform API billing system. It does not alter Enterprise Portal plans or subscriptions.

## Approved launch catalog

| Plan | Monthly fee | Included each month | Additional usage |
|---|---:|---:|---:|
| Developer | $149 | 250,000 API credits | $0.75 per 1,000 credits |
| Scale | $749 | 2,000,000 API credits | $0.35 per 1,000 credits |

The first commercial activation is monthly only. Annual Checkout is intentionally disabled and the Render activation clears both annual Stripe Price IDs.

This boundary is deliberate. The provisional database rows contain annual prices, but the complete annual entitlement and metered-overage lifecycle has not yet been promoted as a separate catalog version. Public pricing stays disabled at the API level so those provisional annual values are not presented as purchasable offers. The authenticated billing page displays only the approved monthly catalog.

## What the workflow provisions

The `Platform API Stripe Activation` workflow creates or safely reuses:

- one Stripe Product for Developer;
- one Stripe Product for Scale;
- one monthly recurring base Price for each plan;
- one Stripe Billing Meter named `agroai_api_credits`;
- one monthly metered overage Price for each plan;
- one Platform API Customer Portal configuration;
- one signed Platform API webhook endpoint;
- the corresponding monthly-only Render configuration;
- the active database plan and operation-cost catalog;
- a redacted activation evidence artifact.

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
- confirmation: `PROVISION AND ACTIVATE AGROAI PLATFORM TEST MONTHLY BILLING`

The workflow must prove all of the following:

- only monthly Stripe Prices were provisioned;
- annual Price IDs were cleared from the selected Render service;
- the billing runtime is healthy;
- an invalid webhook signature returns HTTP 400 rather than a configuration error;
- the operation-cost catalog is active;
- provisional public pricing remains closed;
- an annual Checkout request is denied before Stripe is called;
- an authenticated Developer monthly Checkout session returns a Stripe-hosted URL.

Complete the test Checkout with a Stripe test card, then confirm:

- the webhook marks the API subscription active;
- the customer can open the Stripe Customer Portal;
- an API request creates durable usage;
- usage below the included allowance is not exported as an overage;
- usage above the allowance creates a meter outbox item;
- the outbox exports exactly once;
- the Stripe meter summary reflects the overage event;
- cancellation and payment-failure states reconcile correctly.

### 2. Activate live mode

Run the same workflow with:

- mode: `live`
- action: `provision`
- configure Render: enabled
- deploy: enabled
- activate catalog: enabled
- prove Checkout: enabled
- confirmation: `PROVISION AND ACTIVATE AGROAI PLATFORM LIVE MONTHLY BILLING`

The protected `production` environment must require approval. Review the workflow summary and redacted artifact before approving the job.

### 3. Complete one controlled real purchase

Use an AGRO-AI-owned internal organization. Complete one Developer monthly purchase with a company card. Confirm all of the following before inviting an external customer:

- Checkout displays $149 per month;
- the successful payment returns to Platform API Billing;
- the webhook changes the local subscription to `active`;
- the Stripe invoice and receipt are correct;
- the Customer Portal opens and shows the invoice;
- 250,000 included credits and $0.75 per 1,000 additional credits are shown correctly;
- no annual option is visible or callable;
- no Enterprise Portal subscription was changed;
- no duplicate customer, subscription, invoice, or meter event was created.

Cancel the internal subscription at period end after the proof unless it will remain the permanent billing smoke account.

## Customer experience

Approved Platform developers open:

- standalone: `https://platform.agroai-pilot.com/billing`
- Enterprise Portal: `https://app.agroai-pilot.com/platform/billing`

The page uses the official AGRO-AI identity and shows the approved monthly plans, included credits, metered overage rates, secure Checkout, current subscription state, renewal date, usage access, and the Stripe Customer Portal.

## Rollback

Rollback must stop new purchases without corrupting existing Stripe subscriptions.

1. Set `PLATFORM_API_STRIPE_CHECKOUT_ENABLED=false`.
2. Keep `PLATFORM_API_PRICING_ENABLED=false`.
3. Leave `PLATFORM_API_BILLING_ENABLED=true` while existing webhook events and subscription state still need reconciliation.
4. Leave `PLATFORM_API_STRIPE_METER_EXPORT_ENABLED=true` until all already-recorded billable usage has been exported or explicitly waived.
5. Deactivate the database catalog through the Platform admin endpoint only after Checkout is closed.
6. Do not delete Stripe Products, Prices, Customers, Subscriptions, invoices, meter events, or webhook history.
7. Record the incident, affected organizations, financial exposure, and reconciliation decision.

## Safety properties

- Stripe key mode must match the selected workflow mode.
- Live mutation requires exact confirmation.
- The provisioning client pins Stripe API version `2026-02-25.clover`.
- Stripe Prices are immutable and server-controlled.
- Browser-supplied Price IDs are rejected.
- Annual Price IDs are cleared and annual Checkout is proven closed.
- Checkout creation is organization-scoped and idempotent.
- Stripe webhook signatures and live/test mode are verified.
- Duplicate and out-of-order webhook events cannot regress subscription state.
- Usage exports use durable outbox identifiers and cannot be exported twice.
- Render mutation is restricted to the Platform API billing allowlist.
- Secret files use mode `0600` and are deleted before artifact upload.
- The workflow publishes only redacted evidence.

# AWS Marketplace onboarding checkpoint

For the latest seller-console evidence and controlled test procedure, see
[AWS_MARKETPLACE_COMMERCIAL_RELEASE.md](AWS_MARKETPLACE_COMMERCIAL_RELEASE.md).

**Verified 2026-10-14:** SaaS product `prod-rrjrdndw2eptq` is **Public**
(the October 7 visibility change succeeded). Its `developer` and `scale`
dimensions and fulfillment URL match this integration. This does **not**
establish customer activation: buyer-facing prices/terms and a real
purchase-to-access test remain unverified. The production onboarding flag
is not exposed by the seller screenshots; its configuration default is
`false`. A safe, deliberately token-free production registration probe on
2026-10-14 returned HTTP 400 rather than the disabled-gate HTTP 503, consistent
with the enabled registration handler, **not** a successful buyer purchase.
Do not create duplicate Marketplace entities or declare customer provisioning
verified before a controlled, owner-approved live test.

## Purchase and access lifecycle

AWS posts its form token to `POST /v1/marketplace/aws/register` on the API origin.
The server resolves it with `ResolveCustomer`, verifies the configured product,
and stores the buyer AWS account ID and exact license ARN. It never stores the
purchase token. The response displays a registration reference and a one-hour,
one-time claim code; only the code hash is stored.

An authenticated organization owner or admin can enter both values in the
Developer Console. Linking requires approved organization status and acceptance
of current Platform API terms. One organization can own one AWS license, while
multiple agreements for the same buyer AWS account remain separate and can be
linked to separate organizations. An active Stripe API subscription must be
migrated and outstanding Stripe meter exports must settle before AWS linking,
avoiding two billing owners. The Stripe export worker also refuses to export
usage for an AWS-linked organization.

`License Updated - Manufacturer` is required before activation. The SQS consumer
then uses the Agreement API to verify an ACTIVE purchase agreement, the expected
buyer and product, the exact license ARN, and a PROVISIONED entitlement. API key
access also requires reconciliation within the last 25 hours, an active program
enrollment, current terms, and the existing live access approval. Deprovisioning
and inactive agreement states revoke access. A pending or revoked purchase never
provisions access.

## Deployment configuration

- Apply database migrations through `046_aws_marketplace_plan_mapping`.
- Configure `AWS_MARKETPLACE_PRODUCT_CODE` and `AWS_MARKETPLACE_PRODUCT_ID` from
  the actual seller product, and `AWS_MARKETPLACE_REGION=us-east-1`.
- Use a short-lived seller-account workload identity with `ResolveCustomer` for
  the API and queue/agreement permissions for the worker. Do not create access keys.
- Seller-account OIDC and the CloudFormation/EventBridge/SQS resources have
  been verified. Retain the verified seller account, region and queue configuration.
  Do not recreate infrastructure or replace OIDC with access keys.
- Keep `AWS_MARKETPLACE_EVENTS_ENABLED=true` and
  `AWS_MARKETPLACE_ONBOARDING_ENABLED=false`. Enable onboarding only for a
  controlled test after its commercial prerequisites are satisfied.
- Production runs the bounded SQS consumer and hourly reconciliation inside the
  API process when `AWS_MARKETPLACE_EVENTS_ENABLED=true`. The standalone
  `scripts/process_aws_marketplace_events.py` and
  `scripts/reconcile_aws_marketplace.py` remain safe operator entrypoints.
  Alert on worker failures and dead-letter queue messages. Do not log event bodies,
  purchase tokens, customer identifiers, or SDK exceptions.
- On Render, use managed AWS OIDC with `AWS_ROLE_ARN`; Render supplies
  `AWS_WEB_IDENTITY_TOKEN_FILE` automatically. Do not create long-lived access keys.
  See `AWS_MARKETPLACE_IDENTITY_FIX.md` for the exact seller-account trust policies.

## Remaining release gates

1. Inspect the current public buyer-facing offer: prices, contract term,
   renewal, quantities, EULA and refund terms. Correct `developer`/`scale`
   dimension names and fulfillment URL were confirmed on 2026-10-14, but
   actual buyer charges and terms were not. Do not create a duplicate offer.
2. Verify current runtime `AWS_MARKETPLACE_ONBOARDING_ENABLED` and
   installed migration 046. Latest checked production startup (2026-10-12)
   authenticated to the seller account and called `GetEntitlements`
   successfully; this is not evidence of a completed purchase.
3. Initial AWS Developer and Scale contracts are fixed entitlements. The runtime
   resolves the purchased `developer` or `scale` dimension with
   `GetEntitlements`, maps it to the matching AGRO-AI plan, and blocks overage
   instead of sending Stripe meter events. If a future AWS offer adds usage
   charges, add a durable AWS Marketplace metering outbox before enabling them.
4. The listing is already Public. Complete an approved, bounded real
   purchase-to-access test for organization linking, plan mapping,
   provisioning, usage, changes, cancellation, replay, and failure recovery
   **before general customer onboarding activation**. Do not re-submit
   publication or modify buyer pricing as a substitute for that test.

Official references:
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-product-customer-setup.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_SearchAgreements.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_GetAgreementEntitlements.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_BatchMeterUsage.html

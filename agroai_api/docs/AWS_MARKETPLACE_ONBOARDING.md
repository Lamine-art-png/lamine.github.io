# AWS Marketplace onboarding checkpoint

The staged SaaS product has no offer or pricing terms. Keep onboarding disabled
until approved terms, a deployed seller identity, and a real test purchase are
verified. A code release alone does not authorize a public listing or charges.

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
migrated before AWS linking, avoiding two billing owners.

`License Updated - Manufacturer` is required before activation. The SQS consumer
then uses the Agreement API to verify an ACTIVE purchase agreement, the expected
buyer and product, the exact license ARN, and a PROVISIONED entitlement. API key
access also requires reconciliation within the last 25 hours, an active program
enrollment, current terms, and the existing live access approval. Deprovisioning
and inactive agreement states revoke access. A pending or revoked purchase never
provisions access.

## Deployment configuration

- Apply database migrations through `043_aws_marketplace_linking`.
- Configure `AWS_MARKETPLACE_PRODUCT_CODE` and `AWS_MARKETPLACE_PRODUCT_ID` from
  the actual seller product, and `AWS_MARKETPLACE_REGION=us-east-1`.
- Use a short-lived seller-account workload identity with `ResolveCustomer` for
  the API and queue/agreement permissions for the worker. Do not create access keys.
- Deploy `deploy/aws-marketplace-events.yaml` in the seller account and configure
  `AWS_MARKETPLACE_SELLER_ACCOUNT_ID` and `AWS_MARKETPLACE_QUEUE_URL`.
- Enable `AWS_MARKETPLACE_ONBOARDING_ENABLED` and
  `AWS_MARKETPLACE_EVENTS_ENABLED` only for verified integration testing.
- Run `PYTHONPATH=. python scripts/process_aws_marketplace_events.py` continuously
  or on a frequent schedule, and run
  `PYTHONPATH=. python scripts/reconcile_aws_marketplace.py` at least hourly.
  Alert on worker failures and dead-letter queue messages. Do not log event bodies,
  purchase tokens, customer identifiers, or SDK exceptions.

## Remaining release gates

1. Approve an AWS Marketplace pricing model, dimensions, rates, and applicable
   terms. The draft currently has no offer. The seller public profile review
   must finish before a paid product can be published.
2. Configure short-lived seller-account credentials for the deployed API and
   worker, deploy the migration, and verify exact release health and scheduler.
3. If the approved offer has usage charges, add a durable hourly metering outbox
   mapped to its dimensions. Use `CustomerAWSAccountId` and per-record
   `LicenseArn`, and omit request-level `ProductCode` in `BatchMeterUsage`.
4. Verify a real purchase, organization link, provisioning, usage if applicable,
   changes, cancellation, replay, and failure recovery before AWS review submission.

Official references:
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-product-customer-setup.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_SearchAgreements.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_GetAgreementEntitlements.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_BatchMeterUsage.html

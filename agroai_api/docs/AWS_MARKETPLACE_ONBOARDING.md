# AWS Marketplace onboarding checkpoint

This change is a disabled-by-default token-validation foundation, not a completed
Marketplace integration and not authorization to launch or charge customers.

The planned fulfillment route is `POST /v1/marketplace/aws/register` on the API
origin. Do not enter it in a live offer until deployed and verified with an AWS
test purchase. It accepts the AWS form token, resolves it server-side, validates
the configured product, and stores the AWS account ID and license ARN. Purchase
tokens are not stored. Registration records remain `pending_license`; this
endpoint does not provision API access, link organizations, or charge Stripe.

## Deployment prerequisites

- Apply migration `042_aws_marketplace_registration`.
- Set `AWS_MARKETPLACE_PRODUCT_CODE` to the product's actual code in the secret/configuration store.
- Configure SDK credentials belonging to the AWS seller account, with
  `aws-marketplace:ResolveCustomer` permission. Never put keys in source or chat.
- Set `AWS_MARKETPLACE_REGION=us-east-1`.
- Enable `AWS_MARKETPLACE_ONBOARDING_ENABLED` only for integration testing.

## Remaining launch blockers

1. Confirm contract versus usage-based pricing and the plan/dimension mapping.
2. Configure the current license-based EventBridge events into an SQS queue;
   authenticate events through the AWS queue, not an unauthenticated webhook.
3. Implement durable, idempotent event processing and license-state reconciliation.
   A resolved token alone never activates access. Require `License Updated`.
4. Implement authenticated organization linking, current terms acceptance, and
   concurrent-license handling without bypassing existing organization approval.
5. Route AWS customers exclusively to AWS billing. Block Stripe checkout for any
   organization with AWS billing ownership, including pending purchases.
6. For PAYG, add hourly durable usage export using `CustomerAWSAccountId` and
   `LicenseArn`; omit request-level `ProductCode` in new `BatchMeterUsage` calls.
7. Test buying, linking, API provisioning, usage, license changes, cancellation,
   event replays, and failures before requesting public visibility.

Official references:
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_ResolveCustomer.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_BatchMeterUsage.html
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-product-customer-setup.html

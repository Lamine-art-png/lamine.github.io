# AWS Marketplace onboarding checkpoint

This change is disabled-by-default registration and license-event intake, not a completed
Marketplace integration and not authorization to launch or charge customers.

The planned fulfillment route is `POST /v1/marketplace/aws/register` on the API
origin. Do not enter it in a live offer until deployed and verified with an AWS
test purchase. It accepts the AWS form token, resolves it server-side, validates
the configured product, and stores the AWS account ID and license ARN. Purchase
tokens are not stored. Registration records start `pending_license`; this
endpoint does not provision API access, link organizations, or charge Stripe.
Authenticated queue events transition records to `license_confirmed` or `revoked`.
`license_confirmed` records still have no API entitlement or organization link.
Events arriving before registration are retained; registration does not reset
their state. A revoked license cannot complete registration.

## Deployment prerequisites

- Apply migration `042_aws_marketplace_registration`.
- Set `AWS_MARKETPLACE_PRODUCT_CODE` to the product's actual code in the secret/configuration store.
- Configure SDK credentials belonging to the AWS seller account, with
  `aws-marketplace:ResolveCustomer` permission. Never put keys in source or chat.
- Set `AWS_MARKETPLACE_REGION=us-east-1`.
- Enable `AWS_MARKETPLACE_ONBOARDING_ENABLED` only for integration testing.

## License-event infrastructure and consumer

`deploy/aws-marketplace-events.yaml` defines an EventBridge rule filtered to
this seller and product, an encrypted SQS queue, a 14-day dead-letter queue,
a dead-letter alarm, and least-privilege managed policies. It creates no keys.
The consumer policy can be attached to an existing role using `ConsumerRoleName`;
the separate ResolveCustomer policy must be attached to the registration service
identity. Deploying this template creates AWS resources and requires seller access;
it has not been deployed by this change.

Set `AWS_MARKETPLACE_SELLER_ACCOUNT_ID`, `AWS_MARKETPLACE_QUEUE_URL` from the stack
output, and `AWS_MARKETPLACE_EVENTS_ENABLED=true` only after migration and queue
configuration. Run from the backend root:

```sh
PYTHONPATH=. python scripts/process_aws_marketplace_events.py
```

The command verifies the AWS credential's account through STS, polls a single
bounded queue batch, and commits event receipts and license state before deletion.
It never logs queue payloads, customer IDs, SDK exceptions, or receipt handles.
Failed events remain in SQS for retry and eventual dead-lettering. Duplicates are
idempotent; older events cannot overwrite newer state, and revocation wins equal
timestamps. A scheduler or worker must invoke it continuously and operators must
monitor and replay dead-lettered messages. No scheduler is deployed in this change.
Timestamp ordering is a local guard, not authoritative reconciliation: live
entitlement/Agreement API checks and a recovery policy remain launch requirements.

## Remaining launch blockers

1. Confirm contract versus usage-based pricing and the plan/dimension mapping.
2. Deploy the current license-based EventBridge/SQS template and consumer;
   authenticate events through the AWS queue, not an unauthenticated webhook.
3. Add authoritative license-state reconciliation to the durable event intake.
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

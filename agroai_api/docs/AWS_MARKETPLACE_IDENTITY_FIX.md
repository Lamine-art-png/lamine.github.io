# AWS Marketplace identity repair and runtime bootstrap

This runbook is intentionally non-destructive. It creates no offers, accepts no
Marketplace terms, makes no purchases, and does not enable customer onboarding.

## Verified GitHub OIDC claim

The production `main` workflow emits this subject:

```text
repo:Lamine-art-png/lamine.github.io:ref:refs/heads/main
```

Audience:

```text
sts.amazonaws.com
```

Target AWS Marketplace seller account:

```text
987432215840
```

The diagnostic run on 2026-10-06 proved that the repository's legacy
`AWS_OIDC_ROLE_ARN` pointed to a different AWS account and the legacy
`AWS_REGION` secret was not `us-east-1`. The Marketplace diagnostic no longer
depends on those stale secrets.

## 1. GitHub -> AWS seller-account OIDC

In AWS account `987432215840`, ensure IAM has the OIDC provider:

- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`

Create or update a role for GitHub verification with this trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::987432215840:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:Lamine-art-png/lamine.github.io:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

Attach only read permissions needed by the diagnostic:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:ListStackResources",
        "events:DescribeRule",
        "events:ListTargetsByRule",
        "sqs:GetQueueAttributes",
        "aws-marketplace:DescribeEntity"
      ],
      "Resource": "*"
    }
  ]
}
```

Use the exact role name `AgroAIMarketplaceGitHubVerifier`. The `diag-oidc`
workflow is pinned to the non-secret ARN
`arn:aws:iam::987432215840:role/AgroAIMarketplaceGitHubVerifier` and region
`us-east-1`, so no GitHub AWS role/region secrets are required for this path.

After the role exists, the `diag-oidc` workflow will verify caller account,
CloudFormation, EventBridge, SQS/DLQ and product `prod-rrjrdndw2eptq` without
changing AWS.

## 2. Render -> AWS seller-account OIDC

AGRO-AI's live Render service:

- Workspace: `tea-d8f29999rddc73c7ij1g`
- Environment: `evm-d8f2q6q8qa3s738h6sm0`
- Service: `srv-d8f2q759j78s73fo7bvg`

In AWS account `987432215840`, add the Render OIDC provider:

- Provider URL: `https://oidc.render.com/tea-d8f29999rddc73c7ij1g`
- Audience: `sts.amazonaws.com`

Create a runtime role with this exact-service trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::987432215840:oidc-provider/oidc.render.com/tea-d8f29999rddc73c7ij1g"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.render.com/tea-d8f29999rddc73c7ij1g:aud": "sts.amazonaws.com",
          "oidc.render.com/tea-d8f29999rddc73c7ij1g:sub": "workspace:tea-d8f29999rddc73c7ij1g:environment:evm-d8f2q6q8qa3s738h6sm0:service:srv-d8f2q759j78s73fo7bvg"
        }
      }
    }
  ]
}
```

Attach runtime permissions. AWS Marketplace Metering and Agreement actions do
not support useful seller-product resource scoping, so they use `Resource: "*"`.
The SQS ARN should be tightened to the exact Marketplace event queue after the
read-only diagnostic returns it.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ResolveCustomer",
        "aws-marketplace:SearchAgreements",
        "aws-marketplace:GetAgreementEntitlements"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:987432215840:*"
    }
  ]
}
```

After this role exists, set only `AWS_ROLE_ARN` on the Render service and
redeploy. Render managed OIDC automatically provides
`AWS_WEB_IDENTITY_TOKEN_FILE`; do not set that variable manually and do not
create long-lived AWS access keys.

## 3. Runtime activation order

Do not enable Marketplace flags until the read-only AWS diagnostic succeeds.

Once product code and queue URL are verified, configure the live Render service:

- `AWS_MARKETPLACE_REGION=us-east-1`
- `AWS_MARKETPLACE_SELLER_ACCOUNT_ID=987432215840`
- `AWS_MARKETPLACE_PRODUCT_ID=prod-rrjrdndw2eptq`
- `AWS_MARKETPLACE_PRODUCT_CODE=<verified product code>`
- `AWS_MARKETPLACE_QUEUE_URL=<verified queue URL>`
- `AWS_ROLE_ARN=<Render runtime role ARN>`
- `AWS_MARKETPLACE_EVENT_POLL_SECONDS=60`
- `AWS_MARKETPLACE_RECONCILE_SECONDS=3600`

Keep:

- `AWS_MARKETPLACE_ONBOARDING_ENABLED=false`
- `AWS_MARKETPLACE_EVENTS_ENABLED=false`

until AWS identity, queue and product verification are green.

The application now contains an in-process bounded SQS consumer and hourly
agreement reconciler. After configuration is verified, enable
`AWS_MARKETPLACE_EVENTS_ENABLED=true`, verify worker health/logs, and only then
enable `AWS_MARKETPLACE_ONBOARDING_ENABLED=true` for the controlled Marketplace
purchase/link/cancellation test.

## 4. Explicitly prohibited during setup

Do not:

- create root or long-lived AWS access keys;
- print OIDC tokens or role credentials;
- accept AWS Marketplace legal terms automatically;
- publish or submit the listing automatically;
- create a paid purchase automatically;
- change bank, tax or disbursement data automatically.

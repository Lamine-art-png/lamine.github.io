#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ACCOUNT="987432215840"
GITHUB_PROVIDER_HOST="token.actions.githubusercontent.com"
GITHUB_PROVIDER_URL="https://${GITHUB_PROVIDER_HOST}"
GITHUB_ROLE="AgroAIMarketplaceGitHubVerifier"
GITHUB_SUB="repo:Lamine-art-png/lamine.github.io:ref:refs/heads/main"

RENDER_WORKSPACE="tea-d8f29999rddc73c7ij1g"
RENDER_ENVIRONMENT="evm-d8f2q6q8qa3s738h6sm0"
RENDER_SERVICE="srv-d8f2q759j78s73fo7bvg"
RENDER_PROVIDER_HOST="oidc.render.com/${RENDER_WORKSPACE}"
RENDER_PROVIDER_URL="https://${RENDER_PROVIDER_HOST}"
RENDER_ROLE="AgroAIMarketplaceRenderRuntime"
RENDER_SUB="workspace:${RENDER_WORKSPACE}:environment:${RENDER_ENVIRONMENT}:service:${RENDER_SERVICE}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
if [[ "${ACCOUNT}" != "${EXPECTED_ACCOUNT}" ]]; then
  echo "ERROR: signed into AWS account ${ACCOUNT}; expected seller account ${EXPECTED_ACCOUNT}." >&2
  exit 2
fi
echo "Confirmed AWS seller account ${ACCOUNT}."

ensure_oidc_provider() {
  local host="$1"
  local url="$2"
  local arn="arn:aws:iam::${EXPECTED_ACCOUNT}:oidc-provider/${host}"

  if aws iam get-open-id-connect-provider       --open-id-connect-provider-arn "${arn}" >/dev/null 2>&1; then
    echo "OIDC provider already exists: ${host}"
  else
    aws iam create-open-id-connect-provider       --url "${url}"       --client-id-list sts.amazonaws.com >/dev/null
    echo "Created OIDC provider: ${host}"
  fi

  local audiences
  audiences="$(aws iam get-open-id-connect-provider     --open-id-connect-provider-arn "${arn}"     --query 'ClientIDList' --output text)"
  if ! grep -qw "sts.amazonaws.com" <<<"${audiences}"; then
    aws iam add-client-id-to-open-id-connect-provider       --open-id-connect-provider-arn "${arn}"       --client-id sts.amazonaws.com
    echo "Added sts.amazonaws.com audience: ${host}"
  fi
}

ensure_role() {
  local role_name="$1"
  local trust_file="$2"
  local policy_name="$3"
  local policy_file="$4"

  if aws iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
    aws iam update-assume-role-policy       --role-name "${role_name}"       --policy-document "file://${trust_file}"
    echo "Updated trust policy: ${role_name}"
  else
    aws iam create-role       --role-name "${role_name}"       --assume-role-policy-document "file://${trust_file}"       --description "AGRO-AI AWS Marketplace workload identity" >/dev/null
    echo "Created role: ${role_name}"
  fi

  aws iam put-role-policy     --role-name "${role_name}"     --policy-name "${policy_name}"     --policy-document "file://${policy_file}"
  echo "Applied inline policy: ${role_name}/${policy_name}"
}

TMPDIR_BOOTSTRAP="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_BOOTSTRAP}"' EXIT

GITHUB_TRUST="${TMPDIR_BOOTSTRAP}/github-trust.json"
GITHUB_POLICY="${TMPDIR_BOOTSTRAP}/github-policy.json"
RENDER_TRUST="${TMPDIR_BOOTSTRAP}/render-trust.json"
RENDER_POLICY="${TMPDIR_BOOTSTRAP}/render-policy.json"

cat >"${GITHUB_TRUST}" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${EXPECTED_ACCOUNT}:oidc-provider/${GITHUB_PROVIDER_HOST}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "${GITHUB_PROVIDER_HOST}:aud": "sts.amazonaws.com",
          "${GITHUB_PROVIDER_HOST}:sub": "${GITHUB_SUB}"
        }
      }
    }
  ]
}
JSON

cat >"${GITHUB_POLICY}" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MarketplaceLaunchReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:ListStackResources",
        "events:DescribeRule",
        "events:ListTargetsByRule",
        "sqs:GetQueueAttributes",
        "aws-marketplace:DescribeEntity",
        "aws-marketplace:ListEntities"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InspectMarketplaceRuntimePolicy",
      "Effect": "Allow",
      "Action": [
        "iam:GetRolePolicy"
      ],
      "Resource": "arn:aws:iam::987432215840:role/AgroAIMarketplaceRenderRuntime"
    }
  ]
}
JSON

cat >"${RENDER_TRUST}" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${EXPECTED_ACCOUNT}:oidc-provider/${RENDER_PROVIDER_HOST}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "${RENDER_PROVIDER_HOST}:aud": "sts.amazonaws.com",
          "${RENDER_PROVIDER_HOST}:sub": "${RENDER_SUB}"
        }
      }
    }
  ]
}
JSON

cat >"${RENDER_POLICY}" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MarketplaceRuntime",
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ResolveCustomer",
        "aws-marketplace:SearchAgreements",
        "aws-marketplace:GetAgreementEntitlements",
        "aws-marketplace:GetEntitlements"
      ],
      "Resource": "*"
    },
    {
      "Sid": "MarketplaceEventQueue",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:${EXPECTED_ACCOUNT}:*"
    }
  ]
}
JSON

ensure_oidc_provider "${GITHUB_PROVIDER_HOST}" "${GITHUB_PROVIDER_URL}"
ensure_oidc_provider "${RENDER_PROVIDER_HOST}" "${RENDER_PROVIDER_URL}"

ensure_role   "${GITHUB_ROLE}"   "${GITHUB_TRUST}"   "AgroAIMarketplaceVerificationReadOnly"   "${GITHUB_POLICY}"

ensure_role   "${RENDER_ROLE}"   "${RENDER_TRUST}"   "AgroAIMarketplaceRuntime"   "${RENDER_POLICY}"

echo
echo "AWS Marketplace workload identity bootstrap complete."
echo "GitHub verifier role: arn:aws:iam::${EXPECTED_ACCOUNT}:role/${GITHUB_ROLE}"
echo "Render runtime role: arn:aws:iam::${EXPECTED_ACCOUNT}:role/${RENDER_ROLE}"
echo "No access keys were created. No Marketplace offers, purchases, terms, or payout settings were changed."

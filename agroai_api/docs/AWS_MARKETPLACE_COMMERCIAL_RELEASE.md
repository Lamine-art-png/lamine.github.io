# AWS Marketplace commercial release checkpoint — 2026-10-07

This supersedes older infrastructure blockers in AWS_MARKETPLACE_ONBOARDING.md.
The product is **Draft, not publicly live**. Keep onboarding disabled.
Event processing remains enabled. Use short-lived OIDC credentials only.

## Evidence and completed work

- Owner handoff: seller-account GitHub and Render OIDC work; seller account
  987432215840; region us-east-1; event processing is live.
- Fresh read-only diag-oidc run 37562372875, job 112602303017, completed successfully
  at 02:32 UTC. Product prod-rrjrdndw2eptq revision 3 has Visibility=Draft.
- Product code: ewfyl87ay09pamgkz3pr05d7r.
- Exact entitlement dimension keys: developer and scale; type Entitled; unit Units.
- Catalog fields populated: title, short/long descriptions, three highlights,
  nine keywords, three categories, logo URL, support description, two dimensions.
  Presence does not prove editorial accuracy, URL validity or AWS acceptance.
- AdditionalResources is empty. This finding alone does not prove a required-field failure.
- PR #548 merged the safe read-only commercial diagnostic.
- PR #547 merged at ad802f35ec84726c9c8c74d00e250ee20931ddf2 after all 45 checks
  passed or intentionally skipped. Its startup gate initially failed on a package
  download timeout; the rerun passed migration 046, image build and image startup.
  It maps exact-license AWS entitlements to Developer/Scale plans, disables AWS
  overage, and prevents Stripe from billing AWS usage. Render deployment dep-db2qv695efls73c9ckeg is live on this commit.
  Startup logs confirm migration 045 -> 046 at 02:35:02 UTC and successful startup.
  Health returned 200 and the new instance verified the seller identity.
  A live registration POST returned 503 with onboarding explicitly disabled.

## Exact commercial decisions already approved

| Dimension key | Display name | Monthly price USD | Annual price USD |
|---|---|---:|---:|
| developer | Developer | 149 | 1430 |
| scale | Scale | 749 | 7190 |

Use these approved prices when inspecting/preparing the public offer. Do not copy
direct Stripe overage rates into AWS terms. Confirm AWS contract duration, unit
quantity, renewal behavior and offer schema before writing a changeset. Do not
invent quantity constraints, refund rules, EULA acceptance or buyer eligibility.

## Current access boundary

The fresh audit returned OFFER_INSPECTION=blocked:aws-marketplace:ListEntities.
The verifier role has DescribeEntity but cannot enumerate offers. Consequently,
offer existence, rates, legal terms and public-offer visibility are **unverified**;
do not repeat the historical claim that no offer exists.

Financial onboarding is not exposed by the product Catalog response. The owner
reports that seller information was submitted; current tax, banking and
disbursement approval remain unverified. Do not repeat account setup.

The AWS seller-management page was inaccessible from this session's browser.
The next access step is an authenticated seller-console session or an authorized
OIDC role with commercial Catalog read permissions. No access keys are needed.
An account IAM administrator can add narrowly appropriate ListEntities access
for inspection; DescribeEntity is already available. Creating/updating draft
commercial entities additionally needs authorized StartChangeSet and change-set
status permissions. Do not silently expand the read-only verifier role.

## Remaining inspection / draft preparation

Inspect the actual public Offer entity linked to this product before creating
anything, to avoid duplicate offers. Verify pricing and durations against the
table, EULA/legal terms, refund policy, availability/release dates and renewal
terms. Prepare only draft changes; inspect validation errors and changeset status.

Inspect the actual product fulfillment options and HTTPS registration URL.
Expected application endpoint:
https://api.agroai-pilot.com/v1/marketplace/aws/register
AWS must POST the Marketplace registration form token. Do not substitute the
chatbot or public landing page. Confirm the listing uses the endpoint and handles
the required fulfillment flow before requesting limited availability.

Validate final description, screenshots/logo, support contact, support commitments,
categories, resources and legal URLs against approved organization records.
The diagnostic intentionally logged field presence, not the complete unpublished
copy; therefore editorial/legal review is still pending.

Verify seller tax/banking/disbursement status in the seller console without
printing financial data. Identity attestations, bank changes and terms acceptance
remain account-owner actions.

Before live entitlement tests, verify that the Render runtime role actually has
aws-marketplace:GetEntitlements. PR #547 updates the infrastructure/bootstrap
source; a merged policy file does not establish that live IAM was updated.
Verify deployed migration 046 and exact running commit.

## Controlled integration test — prepared, not executed

Prerequisites: verified offer configuration; AWS-supported limited/test availability;
approved dedicated buyer account and organization; confirmed total purchase cost,
duration, cancellation/refund implications; deployed entitlement mapping and IAM.
A cancellation must not be assumed to issue a refund or immediately end a contract.

Keep onboarding OFF until those conditions hold. For the approved bounded test
window only, enable it with rollback ready; leave event processing ON. This test
window precedes public launch and is not permission to publish the listing.

| Step | Action | Required evidence |
|---|---|---|
| 1 | Owner accepts exact approved test purchase in AWS | Correct product/offer, buyer, dimension, duration and cost; no charge made by the agent |
| 2 | Follow AWS fulfillment POST to registration endpoint | Valid token resolved once; expected product, buyer and exact license; token absent from logs/storage |
| 3 | Sign in as approved organization owner/admin and link claim | One-time claim succeeds; organization terms/access prerequisites satisfied; cross-organization and replay attempts rejected |
| 4 | Process real AWS lifecycle event and reconcile | Exact agreement/license ACTIVE and provisioned; correct Developer or Scale entitlement; no activation from synthetic local success |
| 5 | Use API within purchased plan | Correct credits/resource limits; AWS billing owner; no Stripe meter event or unauthorized overage |
| 6 | Replay event and reconcile twice | Idempotent state; no duplicate subscription, credits or billing |
| 7 | Exercise invalid/expired/mismatched token and unauthenticated link | Access denied without exposing token/customer details |
| 8 | Owner requests approved cancellation/end-of-entitlement action | Actual effective end time recorded; do not assume cancel means immediate revocation |
| 9 | Observe actual revocation/deprovisioning | Queue/reconciliation removes access when AWS entitlement ends; stale credentials cannot use protected API |
| 10 | Check recovery and clean up test access | No unexpected DLQ messages, missing events or Stripe billing; onboarding OFF again pending release approval |

Record timestamps, build SHA, migration head and redacted outcomes in a private
evidence record. Do not commit purchase tokens, claim codes, customer identifiers,
agreement/license identifiers or account financial records to this public repo.

## Publication boundary

Do not request public publication or click Submit until the correct offer, listing,
seller eligibility and controlled lifecycle evidence are ready. If AWS requires
an earlier submission to obtain limited availability, identify that exact screen
and scope and get owner approval before submitting it. Never equate Draft with live.

The exact owner-only button cannot be truthfully identified from Catalog field
presence. Inspect the authenticated console first. Terms acceptance, any purchase
and final submission require the owner at the relevant step; routine technical
verification and preparation should be completed by the agent.

# Intelligence contract billing runbook (internal)

This runbook covers paid pilots and enterprise orders that are invoiced by
AGRO-AI rather than paid by card in the console. It reuses the existing
Intelligence wallet, ledger and per-run debit. There is no second billing
system.

**Preconditions (all required):**
- an accepted written offer;
- the customer's Stripe customer mapped to its AGRO-AI organization
  (`organizations.stripe_customer_id`);
- `INTELLIGENCE_INVOICE_CREDITS_ENABLED=true` on the API service.

## Steps

1. **Invoice in Stripe** (dashboard or API) for the accepted offer, on the
   organization's mapped Stripe customer. Set the invoice metadata:
   - `agroai_organization_id` = the AGRO-AI organization id
   - `agroai_intelligence_credit_cents` = the integer usage credit the offer
     includes. It must be ≤ the amount paid excluding tax. A fee with no usage
     credit, such as an integration fee, needs no wallet credit at all.
2. **Wait for Stripe to mark the invoice `paid`.** Bank transfers can take days.
   Nothing is credited before that.
3. **Post the credit** as a platform admin (founder allowlist):

   `POST /v1/platform-admin/intelligence/invoice-credits`
   `{"organization_id": "...", "stripe_invoice_id": "in_...", "expected_credit_cents": 250000}`

   The server re-reads the invoice from Stripe and refuses unless all of these
   match: customer, `paid` status, USD, live/test mode, both metadata fields,
   your expected credit, and the amount paid excluding tax. On success it posts
   one `topup` ledger entry keyed by the invoice id and adds to the wallet.
   Replays return `already_credited`. One invoice can never fund two
   organizations. Refusals and credits are written to the security audit log.
4. **Activate LIVE access** (separate, gated): approve the organization's LIVE
   access through the existing approval flow. Enable
   `INTELLIGENCE_DMRV_ADVISORY_ENABLED` only after a LIVE smoke test.
5. **Consumption**: each completed `/v1/intelligence` run debits the wallet at
   the task price. Failed or degraded runs are not charged. Insufficient balance
   returns 402. The admission check reconciles a just-paid Checkout before
   refusing.
6. **Reconcile**:

   `GET /v1/platform-admin/intelligence/reconciliation?organization_id=...`

   This returns:
   - wallet totals;
   - ledger totals by kind and status;
   - completed-run charges;
   - provider token/cost totals recorded per run (internal margin telemetry);
   - two consistency checks (`balance_matches_posted_ledger`,
     `completed_runs_match_ledger_charges`).

## Refunds

Refund in Stripe first, then record the business decision. Wallet debits
already consumed are not reversed automatically. Unused prepaid balance is
handled under the agreement's terms.

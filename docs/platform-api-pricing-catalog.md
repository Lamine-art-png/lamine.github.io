# Platform API pricing catalog

Status: direct AGRO-AI production billing is live and production-verified for the Developer and Scale plans. Public acquisition, external marketplace publication, TEST self-service activation, and marketplace-specific entitlement/billing integrations remain separate launch states and must be represented independently.

| Plan | Monthly | Annual | Included credits | Overage |
| --- | ---: | ---: | ---: | ---: |
| Sandbox | $0 | — | 10,000 | none |
| Developer | $149 | $1,430 | 250,000 | $0.75 / 1,000 |
| Scale | $749 | $7,190 | 2,000,000 | $0.35 / 1,000 |
| Enterprise | custom | custom | explicit custom | explicit custom |

Sandbox: one test project, two service accounts, two active keys, one webhook,
seven-day logs. Developer: three projects, one approved live project, five
service accounts/keys, three webhooks, 30-day logs. Scale: ten projects, five
approved live projects, 20 service accounts/keys/webhooks, 90-day logs.

Developer and Scale have live AGRO-AI Stripe base prices and interval-matched
metered overage prices. The AGRO-AI credit ledger remains the synchronous
authorization source; Stripe meter export is asynchronous settlement.

A marketplace-originated subscription must use that marketplace's required
transaction and entitlement path. Do not create a second direct Stripe charge
for the same marketplace subscriber.

Sandbox availability remains controlled by the TEST self-service and legal
activation gates. A configured Stripe catalog does not by itself open public
self-service, and external marketplace readiness must not be inferred from
direct AGRO-AI billing readiness.

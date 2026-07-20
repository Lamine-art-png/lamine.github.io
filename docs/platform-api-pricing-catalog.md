# Provisional Platform API pricing catalog

Status: seeded inactive for test/review. Commercial approval and real test/live
Stripe configuration are required before activation.

| Plan | Monthly | Annual | Included credits | Provisional overage |
| --- | ---: | ---: | ---: | ---: |
| Sandbox | $0 | — | 10,000 | none |
| Developer | $149 | $1,430 | 250,000 | $0.75 / 1,000 |
| Scale | $749 | $7,190 | 2,000,000 | $0.35 / 1,000 |
| Enterprise | custom | custom | explicit custom | explicit custom |

Sandbox: one test project, two service accounts, two active keys, one webhook,
seven-day logs. Developer: three projects, one approved live project, five
service accounts/keys, three webhooks, 30-day logs. Scale: ten projects, five
approved live projects, 20 service accounts/keys/webhooks, 90-day logs.

Catalog rows and operation-credit costs are versioned and inactive by default.
Route code never accepts a browser-supplied Stripe price or amount.

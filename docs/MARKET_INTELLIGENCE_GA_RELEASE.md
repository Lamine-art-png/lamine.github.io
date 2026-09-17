# Market Intelligence GA release contract

This release turns the production-shaped Market Intelligence vertical slice into a customer-usable Enterprise Portal workspace.

## Customer workflow

An authorized customer can now:

1. create a crop or commodity commercial position;
2. enter expected production, carry inventory, cost basis, freight and storage assumptions;
3. add priced or committed commercial contracts;
4. enter a verified customer market price when the exact physical market is not covered by an upstream;
5. refresh governed market sources;
6. receive daily ECB reference FX reconciliation for supported currencies;
7. receive USDA AMS MyMarketNews observations for configured U.S. reports when a USDA API key is present;
8. review source freshness and provenance;
9. run deterministic price, yield, FX and cost scenarios;
10. ask grounded Market Intelligence questions without allowing the model to invent financial arithmetic;
11. retain commercial decisions in the decision journal.

## Data truth contract

- Customer-entered observations are stored as `MANUAL`, never `LIVE`.
- ECB reference FX is stored as `DELAYED` and identified as a reference rate, not an execution rate.
- USDA observations are stored as `DELAYED` government-report evidence.
- A provider observation cannot claim `LIVE` unless verified upstream retrieval metadata is present.
- Upstream evidence is persisted before deterministic economics are recomputed.
- Price observations are promoted into the commercial position only when units are demonstrably compatible.
- Missing credentials or unsupported physical markets remain `NOT_CONFIGURED` or require customer-owned prices; no value is fabricated.

## Release controls

The module remains server-authoritative through:

- `MARKET_INTELLIGENCE_RELEASE_STATE=disabled|internal|canary|general`
- `MARKET_INTELLIGENCE_INTERNAL_ORGANIZATION_IDS`
- `MARKET_INTELLIGENCE_CANARY_ORGANIZATION_IDS`
- entitlement key `market_intelligence.rollout`

General availability should use `MARKET_INTELLIGENCE_RELEASE_STATE=general` with demo fixtures disabled.

## Provider configuration

### ECB FX

No secret is required. The application retrieves the ECB daily reference-rate XML through the governed provider runtime.

### USDA MyMarketNews

Set `USDA_MMN_API_KEY` to a MyMarketNews API key. The adapter uses the API key as the Basic authentication username with an empty password, following USDA's API contract.

The customer can optionally provide a `usda_mmn_slug` in position metadata to identify the exact report. A small supported-region mapping exists for selected U.S. grain reports. The adapter deliberately returns no price rather than guessing when report coverage is ambiguous.

## Operational standard

Market Intelligence is not a brokerage or trade-execution system. It is commercial decision support. Deterministic economics remain available if model synthesis is unavailable, and personalized derivatives instructions remain blocked.

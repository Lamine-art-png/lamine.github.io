# AGRO-AI Market Intelligence

## Product contract

Market Intelligence is the commercial decision layer inside the AGRO-AI Enterprise Portal. It connects customer-owned operational and commercial facts with governed market observations, deterministic economics, scenario analysis, and grounded model synthesis.

The module is intentionally **not** a trading terminal, futures-only product, news feed, or generic chatbot. It must remain useful for row crops, specialty crops, processors, cooperatives, livestock/dairy operations, grower-shippers, and multi-region agricultural enterprises.

The north-star question is: **what changed, what does it mean for this operation's economics, what is exposed, and what deserves attention?**

## Architecture

```text
customer operation / contracts / costs / inventory
                     |
                     v
         canonical commercial position
                     |
       +-------------+-------------+
       |                           |
       v                           v
governed market sources      AGRO-AI operational data
       |                           |
       +-------------+-------------+
                     v
          normalization + provenance
                     v
        deterministic economics engine
           |       |        |
           |       |        +--> data health / confidence inputs
           |       +-----------> exposure + scenario results
           +-------------------> position / margin / break-even
                     |
                     v
             structured evidence
                     |
                     v
        multi-model synthesis gateway
                     |
                     v
         numeric-grounding validation
                     |
                     v
         portal / API / decision journal
```

### 1. Canonical domain model

The persistence layer introduces:

- `market_positions`: crop/commodity position, season, geography, reporting currency, production, inventory, cost, current realizable price, freight and storage economics.
- `market_contract_positions`: contracted quantities and prices with explicit units, currencies and optional FX conversion.
- `market_observations`: time-stamped market evidence with provider, source state, quality and licensing metadata.
- `market_scenarios`: persisted assumptions, baseline and deterministic result.
- `market_decision_journal`: organizational memory around commercial decisions.
- `market_intelligence_insights`: durable structured insight cache/audit foundation.

Every customer row is scoped by `organization_id`; high-value objects are indexed by organization, commodity, season and time.

### 2. Fixed-precision economics

Financial truth is computed in Python with `Decimal`/SQL fixed-precision numerics. An LLM never calculates:

- contracted/uncontracted volume
- weighted contract price
- locked/exposed/projected revenue
- break-even
- projected cost and margin
- quantity conversion
- FX conversion
- scenario deltas

Bushel conversions are commodity-specific. A bushel is never treated as a universal mass unit. Unsupported crop/bushel combinations fail explicitly instead of inventing a conversion.

The engine fails conservatively. Missing contract FX and over-contracting suppress projected revenue and margin rather than publishing a partial total as if it were complete. Currency-grouped portfolio projected totals are also suppressed whenever any constituent position is incomplete. Position costs, freight and storage are entered in the position's reporting currency; realizable prices and contracts in other currencies require explicit FX rates.

Scenario FX changes revalue both the realizable market price and every foreign-currency contract that has a baseline FX rate. Sell-now scenarios are rejected when market price, FX, production or contract reconciliation is incomplete; scenario assumptions never mutate the stored position or contracts.

### 3. Global market structure

The same architecture supports different commercial realities:

- exchange/physical hybrid markets such as corn, soybeans and wheat;
- physical-only or contract-heavy specialty crops such as almonds;
- local market systems where exchange-traded derivatives are not the operator's primary tool;
- multi-currency operations and reporting currencies.

Six explicit synthetic cases exercise Brazil soybeans, U.S. corn, California almonds, Australian wheat, Indian rice and a Kenyan maize cooperative. They are test/demo fixtures, not claims of live market connectivity.

### 4. Source states and provenance

Every market observation has an explicit source state:

- `LIVE`
- `DELAYED`
- `DEMO`
- `STALE`
- `UNAVAILABLE`
- `NOT_CONFIGURED`
- customer/API ingestion may additionally be stored as `MANUAL`

`LIVE` is a privileged state. The provider adapter contract rejects LIVE observations unless verified upstream retrieval metadata is present. Customer-facing structured ingestion cannot grant itself LIVE authority.

Source records carry observation/retrieval timestamps, age, provider/source identity, unit, currency, delay, quality metadata and licensing/display constraints. Observation-list values are redacted whenever licensing explicitly sets `display_allowed` to `false`.

### 5. Provider-neutral market data

`MarketDataProvider` and `MarketDataRegistry` establish the integration boundary for future licensed/configured providers. Exchange, government, FX, physical-price, logistics and crop-estimate providers can be added without changing the commercial engine.

Examples of future provider families include USDA/government reports, properly licensed CME/B3/Euronext/ASX data, physical-market price reporting, FX feeds, freight/storage systems, customer ERP and existing AGRO-AI operational connectors.

No exchange feed is represented as live merely because the architecture knows the exchange name. Licensing and credentials remain separate production prerequisites.

### 6. AI layer

Market Intelligence uses the existing AGRO-AI `ModelRouter`; it does not hard-code one provider or model. The AI layer receives deterministic facts and a bounded evidence map.

Structured output requires every numeric claim to include an evidence ID and the exact evidence value. Validators reject unsupported or modified numbers and personalized derivatives instructions. If the model is unavailable, malformed, or fails grounding or policy validation, the product falls back to deterministic briefing instead of losing the commercial position.

This means an AI outage can remove natural-language synthesis, but not position, margin, exposure, scenarios or source health.

### 7. Regulatory boundary

Version 1 is commercial decision support. It does not:

- execute trades;
- connect to brokerage execution;
- instruct a customer to enter a specific derivatives position;
- represent scenarios as predictions.

Scenario language such as "lock another 20% at the current structured price" is an economics simulation, not an execution instruction. Any future personalized derivatives-advice or execution feature requires separate legal/compliance review and an explicit product boundary.

## API surface

Authenticated routes are under `/v1/market-intelligence`:

- `GET /overview`
- `GET /positions`
- `GET /positions/{id}`
- `POST /positions`
- `POST /contracts`
- `POST /observations`
- `POST /scenarios`
- `GET /scenarios`
- `GET /scenarios/{id}`
- `POST /ask`
- `POST /decision-journal`
- `GET /decision-journal`
- `POST /demo/seed` (admin; production-safe gated)

Client payloads never choose an organization. The organization is derived from authenticated server context. Cross-tenant resource identifiers resolve as 404 to avoid disclosing another customer's objects.

## Portal

The Enterprise Portal exposes `/market-intelligence` with:

- portfolio economics grouped by reporting currency;
- position selector and commercial KPIs;
- material attention items;
- deterministic scenario lab;
- grounded conversational intelligence;
- source/data-health view;
- DEMO labeling and commercial-decision-support notice.

Portfolio totals are never added across different currencies. Portfolio dependencies are batch-loaded by organization to avoid per-position contract and observation queries.

## Rollout

Server-authoritative release states:

- `disabled`
- `internal`
- `canary`
- `general`

Production/staging fail closed when a valid release configuration is absent. Cohorts can be controlled through server-side organization lists and the entitlement override `market_intelligence.rollout`.

Environment controls:

```text
MARKET_INTELLIGENCE_RELEASE_STATE=disabled|internal|canary|general
MARKET_INTELLIGENCE_INTERNAL_ORGANIZATION_IDS=
MARKET_INTELLIGENCE_CANARY_ORGANIZATION_IDS=
MARKET_INTELLIGENCE_DEMO_FIXTURES_ENABLED=false
```

## Current production boundary

The production-shaped module, deterministic engine, persistence, authentication/tenancy, scenario system, grounded multi-model layer, global demo fixtures, provider contracts and portal surface can ship independently of paid market feeds.

**Live market connectivity is not complete until a real provider adapter is configured with credentials/licensing, freshness policies and verified upstream retrieval.** The product must display `DEMO`, `MANUAL`, `STALE`, `DELAYED`, `UNAVAILABLE` or `NOT_CONFIGURED` honestly until those conditions are met.

## Next provider work

The next production integration phase should prioritize provider coverage by customer decision value, not geography alone:

1. FX source with explicit timestamps and retry/circuit-breaker policy.
2. U.S. government/cash-market sources and licensed benchmark data where required.
3. Brazil physical/benchmark/FX sources under appropriate data rights.
4. specialty-crop physical-market sources.
5. Australia/Europe/India/Africa regional adapters as customers require them.
6. background refresh, caching/materiality detection and alert delivery on top of the time-series observations already persisted.

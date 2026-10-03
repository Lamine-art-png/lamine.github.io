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

Marketable supply is `expected production + carry inventory`. Contract coverage, uncontracted quantity and projected revenue use that supply consistently. Baseline production cost is fixed at the baseline yield by default, so yield scenarios change unit economics without silently scaling total production cost. Inventory margin is included only when an explicit inventory cost per unit is present; otherwise revenue remains visible while margin and break-even are suppressed as incomplete.

The engine fails conservatively. Missing contract FX and over-contracting suppress projected revenue and margin rather than publishing a partial total as if it were complete. Currency-grouped portfolio projected totals are also suppressed whenever any constituent position is incomplete. Position costs, freight and storage are entered in the position's reporting currency; realizable prices and contracts in other currencies require explicit FX rates.

Scenario FX changes use one quote convention: **reporting currency per one unit of source currency**. A positive FX percentage therefore increases the reporting-currency value of both the realizable market price and every foreign-currency contract that has a baseline FX rate. Sell-now scenarios are rejected when market price, FX, production or contract reconciliation is incomplete; scenario assumptions never mutate the stored position or contracts.

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

Data health derives effective staleness from observation age and each source's freshness policy; a declared `LIVE` status cannot override an expired freshness window. Missing freshness policy, low provider quality and mixed demo/live evidence degrade confidence conservatively. Manual and delayed evidence can never produce high confidence.

### 5. Provider-neutral market data

`MarketDataProvider` and `MarketDataRegistry` establish the integration boundary for future licensed/configured providers. Exchange, government, FX, physical-price, logistics and crop-estimate providers can be added without changing the commercial engine.

Examples of future provider families include USDA/government reports, properly licensed CME/B3/Euronext/ASX data, physical-market price reporting, FX feeds, freight/storage systems, customer ERP and existing AGRO-AI operational connectors.

No exchange feed is represented as live merely because the architecture knows the exchange name. Licensing and credentials remain separate production prerequisites.

Provider calls are wrapped by a bounded timeout/retry/cache/circuit-breaker boundary that preserves adapter provenance and never manufactures observations. The catalog exposes USDA MyMarketNews and FX reference entries as `NOT_CONFIGURED` until approved upstream access exists; an empty result from those entries is not represented as live data.

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

## Commercial Intelligence platform (October 2026)

The module now runs as a global Commercial Intelligence layer:

```text
GLOBAL MARKET DATA PLANE            (shared, tenant-free)
  provider adapters (series level) -> normalization -> market_data_series / market_data_points
  scheduled cycle (hourly cron)     -> market_provider_runs (health, backoff, idempotency)
            |
            v  governed resolution (freshness + licence aware; never synchronous for slow sources)
TENANT COMMERCIAL POSITION GRAPH    (organization-scoped)
  positions, contracts, inventory, costs, linked fields, yield estimates, manual prices
            |
            v
DETERMINISTIC ECONOMICS (Decimal) -> snapshots -> MATERIALITY ENGINE -> alerts / digests
            |                                              |
            v                                              v
SCENARIO ENGINE v2 + HISTORICAL RISK CONTEXT         COMMERCIAL HOME / DATA HEALTH
            |
            v
GROUNDED AI (explains, never calculates) -> Ask AGRO-AI, decision journal
```

### Shared market-data plane

- `app/services/market_data_adapters.py`: series-level adapters. Each emits canonical upstream series (one CONAB state/product/week, one EC market/stage/week, one ECB currency/day) with provider, native id, unit, currency, observed/retrieved time, freshness and last-known policy, and licensing flags. Adapters never emit `LIVE`.
- `app/services/market_data_plane.py`: idempotent persistence (unique series + observation time; changed upstream values become tracked revisions), provider runs with exponential backoff (capped at 24 h), cross-tenant demand de-duplication, freshness states (`DELAYED` fresh, `STALE` within the explicit last-known policy, `UNAVAILABLE` otherwise and never used), FX resolution (BCB PTAX for USD/BRL, ECB cross rates via EUR, exact CFA-franc parity) and physical-price resolution (exact market match, otherwise median of fresh markets, with every contributing point recorded).
- `app/services/market_normalization.py`: multilingual commodity aliases, unit canonicalization (tonne, kg, bushel, pound, quintal, cwt, short/long ton, 60 kg saca, 90/50 kg bags), locale-aware number parsing that refuses ambiguous values, country currency/timezone defaults.
- Licensing is enforced in code: `storage_allowed=false` evidence is never persisted, `derived_values_allowed=false` evidence is never used in calculations, `display_allowed=false` values are redacted in every API response.

### Market Packs

`app/services/market_packs.py` maps country + commodity (or commodity family) to market structure, default unit, futures role and evidence plan. Futures are always optional licensed evidence; specialty crops, mandi and local-market packs have no futures dependency. Onboarding infers the pack, unit, currency and sources from plain answers (crop, country, region, season); customers never supply provider report identifiers. Packs: `br_grains_oilseeds`, `br_coffee`, `us_row_crops`, `us_specialty_crops`, `eu_cereals_oilseeds`, `au_grains`, `in_mandi`, `ke_local_markets`, `waemu_local_markets`, `global_livestock_dairy`, `global_physical` (fallback).

### Positions and refresh

`app/services/market_intelligence_refresh.py` resolves each position from the shared plane. A customer-entered price (`price_policy: manual`) is never overwritten; a customer-supplied FX rate is never cleared when no governed source exists (e.g. KES); automation-set values that can no longer be verified are cleared rather than silently aged. Every promoted value writes a tenant-scoped audit observation pointing at the shared series/point.

### Materiality Engine

`app/services/market_materiality.py` (methodology `materiality-2026.10.1`): snapshots deterministic economics, compares with the reference snapshot (latest at least 20 h old), measures impact as the change in projected margin (or exposed revenue) relative to projected revenue, attributes it to drivers by sequential substitution (contributions sum exactly), and assigns LOW/MEDIUM/HIGH/CRITICAL from configurable thresholds (defaults 2/5/10 %) plus qualitative transitions (margin turning negative, price below break-even, over-contracting). Economic alerts computed from STALE or UNAVAILABLE evidence are suppressed and surfaced as data-quality changes. Events are deduplicated and rate-limited (12 h cooldown unless the level escalates).

### Background cycle and alerts

`app/services/market_intelligence_cycle.py` runs after every hourly maintenance call (`/v1/internal/queue/drain-outbox`, as a background task) and on demand (`/v1/internal/queue/market-cycle`, queue token). It holds a PostgreSQL advisory lock, ingests due demands once for all tenants, re-resolves positions without provider calls, evaluates materiality and persists events (in-app). Email digests to owners/admins are opt-in (`MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED`), exist for en/pt/es/fr, and are deferred (never sent in English) for other languages. Disable the whole cycle with `MARKET_INTELLIGENCE_CYCLE_ENABLED=false`.

### Scenarios, risk, journal

- Scenario Engine v2 adds basis/premium, inventory, carry (months x cost), contracted-volume and lock-price levers, full deltas, completeness and warnings; zero change reproduces the baseline exactly. `POST /scenarios/compare` runs up to six side by side without persisting.
- `app/services/market_risk.py` (`historical-moves-2026.10.1`) reports historical move percentiles, annualised volatility, price percentile and a rolling out-of-sample p5..p95 coverage diagnostic for the governed series behind a position, and stress-tests the position at p5/p95. Minimum 26 observations. Not a forecast.
- Decision Journal v2 freezes the position, data health and scenario at decision time and records the action taken and later outcome versus the modelled margin.

### Field-to-commercial linkage

Positions can be linked to organization fields (`platform_field` entities). Linked area (excluding synthetic/demo fields) x a yield estimate (customer, Field Intelligence, Crop Intelligence or connector source) recalculates expected production and immediately evaluates materiality. AGRO-AI does not yet produce automated yield estimates; the endpoint is the integration point.

### Ask AGRO-AI

What-if questions with explicit percentages (English, Portuguese, Spanish, French) are parsed deterministically, computed by the scenario engine and supplied as evidence ids the model must cite exactly; the deterministic fallback states the same numbers. Open material changes, evidence freshness, the current price source and saved scenarios are supplied as facts. Without a position id, Ask focuses on the position that most deserves attention. Customer-visible traces never name the serving model vendor.

See `docs/COMMERCIAL_INTELLIGENCE_COVERAGE.md` for the exact provider coverage, validation status and remaining credentials/licences.

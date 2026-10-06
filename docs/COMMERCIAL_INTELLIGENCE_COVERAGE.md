# Commercial Intelligence — provider coverage and remaining access

Status as of 2026-10-03. "Live verified" means the adapter was run against the real upstream on that date and produced parsed, normalized points; it does **not** mean the source is real-time. No adapter emits `LIVE`; published sources are `DELAYED` and become `STALE`/`UNAVAILABLE` by their freshness policy.

## Providers with working access (no credential required)

| Provider id | Source | Coverage | Frequency / freshness policy | Licence | Validation |
|---|---|---|---|---|---|
| `fx_reference` | European Central Bank euro reference rates (90-day history) | ~30 currencies vs EUR, cross rates via EUR; CFA franc (XOF/XAF) by legal parity 655.957 | Business-daily; fresh 3 days, last-known 7 days | ECB statistics reuse, attribution | Live verified 2026-10-03 (1,885 points) |
| `bcb_ptax` | Banco Central do Brasil PTAX (selling rate) | Official USD/BRL | Business-daily; fresh 3 days, last-known 7 days | BCB open data, attribution | Live verified 2026-10-03 (latest 5.2238 BRL/USD, 2 Oct) |
| `eu_agrifood` | European Commission agri-food weekly representative prices | EU member states: wheat (breadmaking/feed), durum, barley, maize, oats, sorghum, rapeseed, sunflower, soybeans; per market and marketing stage | Weekly; fresh 14 days, last-known 30 days | Commission reuse (Decision 2011/833/EU, CC BY 4.0) | Live verified 2026-10-03 (e.g. FR breadmaking wheat, Rouen €244.36/t, week to 27 Sep) |
| `conab_precos` | CONAB weekly state prices (`PrecosSemanalUF.txt`) | Brazil, by state: soybean, corn (em grãos), wheat, rice, coffee, beans, cotton — price **received by producers** only | Weekly; fresh 14 days, last-known 30 days. Scheduled ingestion only (the portal serves ~12 MB slowly) | CONAB open data, attribution | Live verified 2026-10-03 (MT soybean R$2.36/kg, week to 25 Sep) |

## Providers implemented but NOT_CONFIGURED (free credential required)

| Provider id | Source | Credential (environment variable) | Validation |
|---|---|---|---|
| `usda_mymarketnews` | USDA AMS MyMarketNews / MARS cash prices | `USDA_MMN_API_KEY` (free MyMarketNews account) | Documented schema fixtures; earlier adapter shipped in production |
| `usda_nass` | USDA NASS Quick Stats state yield statistics | `USDA_NASS_API_KEY` (free) | Documented schema fixtures only |
| `india_agmarknet` | AGMARKNET daily mandi prices via data.gov.in | `DATA_GOV_IN_API_KEY` (free registration) | Documented schema fixtures only; never validated against the live API |

## Adapter boundaries without access (truthfully NOT_CONFIGURED)

| Provider id | Source | Why not configured |
|---|---|---|
| `cme_futures` | CME Group / CBOT futures | Commercial market-data licence and entitlement feed required |
| `b3_futures` | B3 agricultural futures | Commercial licence required |
| `euronext_futures` | Euronext (MATIF) futures | Commercial licence required |
| `asx_futures` | ASX grain futures | Commercial licence required |
| `ice_futures` | ICE softs (coffee, cocoa, sugar) | Commercial licence required |
| `cepea_indicators` | CEPEA/ESALQ indicators | Licence required for commercial reuse/redistribution |
| `au_physical_grain` | Australian physical grain prices | No public machine-readable feed identified |
| `kenya_kamis` | Kenya KAMIS | Web pages only; no documented API |
| `kenya_cbk_fx` | Central Bank of Kenya indicative rates | Web pages only; KES is not in the ECB basket |
| `local_market_manual` | Customer-verified prices | Customer input path, always `MANUAL` |

Evaluated and not adopted: WFP market prices on HDX (CC BY-IGO) — the published extracts end in December 2023 (Kenya), March 2020 (Senegal) and August 2014 (India), so they cannot serve as current evidence. World Bank Pink Sheet — monthly XLSX at a URL that changes each release; deferred.

## Market packs and what each market gets today

| Market | Pack | Physical evidence | FX | Futures |
|---|---|---|---|---|
| Brazil soybean/corn/wheat/rice/coffee | `br_grains_oilseeds` / `br_coffee` | CONAB by state (working) | PTAX + ECB (working) | B3/CME/ICE optional, not licensed |
| United States corn/soy/wheat | `us_row_crops` | USDA MyMarketNews (needs key) or customer price | n/a (USD) | CME optional, not licensed |
| California almonds and specialty crops | `us_specialty_crops` | Customer/contract pricing; USDA where published (needs key) | n/a | None required |
| France and EU cereals/oilseeds | `eu_cereals_oilseeds` | EC weekly prices (working) | ECB (working) | Euronext optional, not licensed |
| Australia wheat | `au_grains` | Customer price (no public feed) | ECB AUD (working) | ASX optional, not licensed |
| India rice and mandi crops | `in_mandi` | AGMARKNET (needs key) or customer price | ECB INR (working) | None required |
| Kenya maize | `ke_local_markets` | Customer price | Customer-supplied rate (no governed KES source) | None required |
| Senegal / CFA-franc countries | `waemu_local_markets` | Customer price | Exact EUR parity + ECB (working) | None required |
| Livestock / dairy | `global_livestock_dairy` | Customer/processor price | ECB | CME optional, not licensed |
| Anywhere else | `global_physical` | Customer price | ECB where covered | None |

## Remaining third-party access, data and human actions

1. **USDA MyMarketNews key** (`USDA_MMN_API_KEY`) to activate U.S. cash prices.
2. **USDA NASS key** (`USDA_NASS_API_KEY`) to activate U.S. state yield context.
3. **data.gov.in key** (`DATA_GOV_IN_API_KEY`) to activate India mandi prices; the adapter then needs a first live validation.
4. **Exchange licences** (CME, B3, Euronext, ASX, ICE) for benchmark/futures evidence; each adapter boundary exists but fetches nothing.
5. **CEPEA licence** for Brazilian physical indicators beyond CONAB.
6. **A licensed or public Australian physical grain feed** and a **machine-readable KES FX source**.
7. **Authenticated production smoke:** set the `MARKET_INTELLIGENCE_SMOKE_TOKEN` repository secret to a real AEP session for an organization in the Market Intelligence release cohort, then run the *Market Intelligence Authenticated Smoke* workflow. Production has no QA tenant; an operator must invite a test mailbox.
8. **Optional:** set `MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED=true` to send HIGH/CRITICAL digests by email (in-app alerts work without it).
9. **Edge gateway deploy:** the scheduled cycle uses the `market_intelligence_cycle` queue task type, which the Cloudflare edge gateway must allow (`cloudflare/edge-gateway/src/index.ts`, deployed by *Deploy Platform API Edge* on merge). Until the edge is deployed, cycle jobs stay safely pending in `task_outbox` and publish with backoff once it is.

Every ISO 3166-1 country (plus Kosovo) and ISO 4217 tender currency is accepted at onboarding (`shared/registries/`); rows above are the countries with a specific Market Pack, and every other country uses `global_physical`.

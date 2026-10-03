# Market Intelligence production release checklist

- [x] deterministic economics engine and scenario semantics
- [x] organization-scoped persistence and RBAC
- [x] managed Enterprise Portal workflow for positions, contracts and manual prices
- [x] governed provider status and refresh controls
- [x] daily ECB reference FX adapter
- [x] USDA MyMarketNews adapter with explicit credential requirement
- [x] provider retries, timeout, cache and circuit breaker
- [x] provenance and source-state truthfulness
- [x] customer input cannot self-label LIVE
- [x] source/unit compatibility gate before automatic price promotion
- [x] grounded model synthesis with deterministic fallback
- [x] derivatives/execution boundary
- [x] route/OpenAPI uniqueness tests
- [x] frontend contract tests
- [x] provider adapter tests
- [x] merge only after branch CI is green or remaining failures are proven repository-wide/pre-existing
- [x] deploy exact merged GA SHA `d996fac5cdcbffec0103a880d71da0e5d2d02272`
- [x] set `MARKET_INTELLIGENCE_RELEASE_STATE=general`
- [x] keep `MARKET_INTELLIGENCE_DEMO_FIXTURES_ENABLED=false`
- [ ] verify authenticated production portal and Market Intelligence API smoke — tooling exists (`scripts/market_intelligence_authenticated_smoke.py`, *Market Intelligence Authenticated Smoke* workflow); it needs the `MARKET_INTELLIGENCE_SMOKE_TOKEN` secret for a real AEP session and has **not** been run against production

## Commercial Intelligence (October 2026)

- [x] shared market-data plane (series, points, provider runs) with idempotent ingestion and revisions
- [x] market packs and customer-language onboarding (no provider identifiers)
- [x] ECB 90-day FX, BCB PTAX, EU agri-food weekly prices and CONAB weekly producer prices live-verified on 2026-10-03
- [x] USDA MyMarketNews, USDA NASS and AGMARKNET adapters implemented; NOT_CONFIGURED until keys are set
- [x] licensed exchange/indicator adapters exist as truthful NOT_CONFIGURED boundaries
- [x] materiality engine, deduplicated alerts, hourly background cycle, opt-in email digests
- [x] Scenario Engine v2, historical risk context, Decision Journal v2, field-to-commercial linkage
- [x] Commercial Intelligence home, provenance, mobile and RTL browser contracts
- [ ] production evidence that the hourly cycle populated the shared plane after deploy (requires an authenticated session or operator database access)

## Production evidence — 2026-09-17

- PR #465 shipped the production-shaped Market Intelligence vertical slice.
- PR #471 completed the customer-operable GA workflow and merged as `d996fac5cdcbffec0103a880d71da0e5d2d02272`.
- The exact GA merge SHA was deployed successfully on Render before the final runtime flag cutover.
- Market Intelligence Final Gate and Market Intelligence GA CI passed on the GA head.
- Database preflight, Alembic revision, PostgreSQL adoption, production-startup, distributed-runtime and portal production-build contracts passed.
- Runtime configuration is explicitly `general` with demo fixtures disabled.
- The post-cutover deployment from current `main` completed successfully; `alembic upgrade head` ran on PostgreSQL, application startup completed, and the replacement instance returned `GET /v1/health` with HTTP 200.
- The remaining authenticated smoke item requires a real logged-in AEP customer/operator session; it must not be marked complete from CI or unauthenticated health evidence alone.

## Intentional data boundary

GA does not claim universal live market coverage. ECB reference FX is governed and available without a secret. USDA MyMarketNews is used only when a real `USDA_MMN_API_KEY` is configured. Other physical markets remain usable through governed customer-owned prices and explicit source-state/provenance handling rather than fabricated live values.

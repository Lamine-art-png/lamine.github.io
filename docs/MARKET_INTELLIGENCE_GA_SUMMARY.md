# Market Intelligence GA completion summary

This branch completes the customer-facing operating loop for AGRO-AI Market Intelligence inside the Enterprise Portal.

It adds a managed portal surface for creating positions, contracts and manual physical-market prices; automatic governed FX refresh through the ECB reference-rate publication; configurable USDA AMS MyMarketNews ingestion; tenant-scoped refresh and management endpoints; route/OpenAPI uniqueness tests; provider adapter tests; and release documentation.

The product continues to fail closed on unsupported markets or missing credentials. It never fabricates live prices, never allows customer input to claim LIVE authority, and never lets model synthesis replace deterministic financial arithmetic.

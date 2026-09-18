# Market Intelligence GA status

Market Intelligence is merged and released to the production backend.

## Current state

- GA implementation: merged through PR #471
- GA merge SHA: `d996fac5cdcbffec0103a880d71da0e5d2d02272`
- Runtime release state: `general`
- Demo fixtures: disabled
- Production database migration: applied successfully through `alembic upgrade head`
- Replacement production instance: started successfully and passed `/v1/health`
- Market Intelligence Final Gate: passed
- Market Intelligence GA CI: passed

## Data coverage

- ECB daily reference FX: active governed provider
- USDA AMS MyMarketNews/MARS: active when `USDA_MMN_API_KEY` is configured
- Other physical markets: governed customer-owned observations/manual prices until a licensed provider is configured
- Unsupported or unavailable sources remain explicit; the product does not fabricate live market data

## Remaining verification

A final authenticated end-user smoke inside a real logged-in AEP session should verify the complete browser loop: open Market Intelligence, create or inspect a position, refresh providers, run a scenario, and use grounded Ask Market Intelligence. This remains a session-bound production check rather than a code/CI blocker.
